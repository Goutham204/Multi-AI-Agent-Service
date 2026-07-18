import json
import os
import re
import time
import datetime
import uuid
import logging
from decimal import Decimal
from groq import Groq

# AWS DYNAMODB INTEGRATION

import boto3

dynamodb = boto3.resource('dynamodb')
orders_table = dynamodb.Table('orders')  
refunds_table = dynamodb.Table('refunds')  
tickets_table = dynamodb.Table('tickets')  

# LOGGING SETUP

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log_request(service_type, user_request, status, details=""):
    logger.info(json.dumps({
        'service': service_type,
        'request_length': len(user_request),
        'status': status,
        'details': details,
        'timestamp': datetime.datetime.now().isoformat()
    }))

# CONSTANTS

ALLOWED_ORIGINS = [
    "https://d2wrk5t4qmgduv.cloudfront.net",  
    "http://localhost:5000",
    "http://localhost:3000"
]

MAX_RETRIES = 3
RETRY_DELAY = 1

# VALIDATION & UTILITY FUNCTIONS

def extract_json_from_response(response_text):
    
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass
    
    json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    
    return None


def validate_financial_request(customer_data):
    
    errors = []
    
    income = customer_data.get('income', 0)
    if not isinstance(income, (int, float)):
        errors.append("Income must be a number")
    elif income <= 0:
        errors.append("Income must be positive")
    elif income > 1000000:
        errors.append("Income exceeds maximum limit")
    
    credit_score = customer_data.get('credit_score', 0)
    if not isinstance(credit_score, (int, float)):
        errors.append("Credit score must be a number")
    elif credit_score < 0 or credit_score > 900:
        errors.append("Credit score must be between 0-900")
    
    loan_amount = customer_data.get('loan_amount', 0)
    if not isinstance(loan_amount, (int, float)):
        errors.append("Loan amount must be a number")
    elif loan_amount <= 0:
        errors.append("Loan amount must be positive")
    elif loan_amount < 1000:
        errors.append("Minimum loan amount: AED 1,000")
    elif loan_amount > 1000000:
        errors.append("Maximum loan amount: AED 1,000,000")
    
    term_months = customer_data.get('term_months', 0)
    if not isinstance(term_months, (int, float)):
        errors.append("Term must be a number")
    else:
        term_months = int(term_months)
        if term_months <= 0:
            errors.append("Term must be positive")
        elif term_months < 6:
            errors.append("Minimum term: 6 months")
        elif term_months > 240:
            errors.append("Maximum term: 240 months (20 years)")
    
    employment = customer_data.get('employment_status', '').lower()
    if employment not in ['employed', 'self_employed', 'unemployed']:
        errors.append("Invalid employment status")
    
    name = customer_data.get('name', '').strip()
    if not name or len(name) < 2:
        errors.append("Customer name is required")
    
    return errors


def call_groq_with_retry(client, model, messages, max_tokens):
    
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens
            )
            return response
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Groq API call failed, retry {attempt + 1}: {str(e)}")
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"Groq API failed after {MAX_RETRIES} retries: {str(e)}")
                raise

# FINANCIAL AGENT CODE

def check_eligibility(income, credit_score, employment_status):
    
    if employment_status == "unemployed":
        return {
            "eligible": False,
            "reason": "Unemployed applicants not eligible"
        }
    
    if income < 3000:
        return {
            "eligible": False,
            "reason": f"Income AED {income} below minimum AED 3,000"
        }
    
    if credit_score < 550:
        return {
            "eligible": False,
            "reason": f"Credit score {credit_score} below minimum 550"
        }
    
    max_loan = min(int(income * 12), 500000)
    
    return {
        "eligible": True,
        "reason": f"Income AED {income} + Credit {credit_score} + Employment OK",
        "max_loan": max_loan
    }


def calculate_interest_rate(credit_score, loan_amount, term_months):
    
    loan_amount_decimal = Decimal(str(loan_amount))
    term_months_decimal = Decimal(str(term_months))
    
    if credit_score >= 750:
        base_rate = Decimal('3.5')
    elif credit_score >= 700:
        base_rate = Decimal('4.5')
    elif credit_score >= 650:
        base_rate = Decimal('5.5')
    else:
        base_rate = Decimal('7.0')
    
    if loan_amount_decimal > Decimal('250000'):
        base_rate += Decimal('0.5')
    
    monthly_rate = base_rate / Decimal('100') / Decimal('12')
    n = term_months_decimal
    
    if monthly_rate == 0:
        monthly_payment = loan_amount_decimal / n
    else:
        monthly_payment = (
            loan_amount_decimal * monthly_rate * (1 + monthly_rate)**n / 
            ((1 + monthly_rate)**n - 1)
        )
    
    total_paid = monthly_payment * term_months_decimal
    total_interest = total_paid - loan_amount_decimal
    
    return {
        "interest_rate_annual": float(base_rate),
        "monthly_payment": float(round(monthly_payment, 2)),
        "total_paid": float(round(total_paid, 2)),
        "total_interest": float(round(total_interest, 2)),
        "term_months": term_months
    }


def generate_offer(customer_name, loan_amount, interest_rate, monthly_payment, term_months):
    
    offer_id = f"LOA-{uuid.uuid4().hex[:8].upper()}"
    
    return {
        "offer_id": offer_id,
        "customer_name": customer_name,
        "loan_amount": loan_amount,
        "interest_rate_annual": interest_rate,
        "monthly_payment": monthly_payment,
        "term_months": term_months,
        "status": "APPROVED - Ready for signature",
        "valid_days": 30,
        "offer_date": datetime.datetime.now().strftime("%Y-%m-%d")
    }


def process_financial_request(user_request, groq_api_key):
    
    try:
        client = Groq(api_key=groq_api_key)
        
        extraction_prompt = f"""Extract customer details from this loan application:

{user_request}

Respond ONLY with JSON (no other text):
{{
    "name": "Customer name",
    "income": numeric_monthly_income_only,
    "credit_score": numeric_score_only,
    "employment_status": "employed or self_employed or unemployed",
    "loan_amount": numeric_amount_only,
    "term_months": numeric_months_only
}}"""
        
        extraction_response = call_groq_with_retry(
            client, 
            "llama-3.1-8b-instant",
            [{"role": "user", "content": extraction_prompt}],
            300
        )
        
        response_text = extraction_response.choices[0].message.content
        customer_data = extract_json_from_response(response_text)
        
        if not customer_data:
            log_request("financial", user_request, "ERROR", "Failed to parse customer details")
            return {"status": "ERROR", "reason": "Failed to parse customer details"}
        
        validation_errors = validate_financial_request(customer_data)
        if validation_errors:
            log_request("financial", user_request, "VALIDATION_ERROR", str(validation_errors))
            return {
                "status": "ERROR",
                "reason": f"Invalid input: {'; '.join(validation_errors)}"
            }
        
        eligibility = check_eligibility(
            customer_data['income'],
            customer_data['credit_score'],
            customer_data['employment_status']
        )
        
        if not eligibility['eligible']:
            log_request("financial", user_request, "DENIED", eligibility['reason'])
            return {
                "status": "DENIED",
                "reason": eligibility['reason']
            }
        
        max_loan = eligibility['max_loan']
        if customer_data['loan_amount'] > max_loan:
            log_request("financial", user_request, "DENIED", f"Loan exceeds max {max_loan}")
            return {
                "status": "DENIED",
                "reason": f"Requested loan AED {customer_data['loan_amount']} exceeds maximum AED {max_loan}"
            }
        
        rate_info = calculate_interest_rate(
            customer_data['credit_score'],
            customer_data['loan_amount'],
            customer_data['term_months']
        )
        
        offer = generate_offer(
            customer_data['name'],
            customer_data['loan_amount'],
            rate_info['interest_rate_annual'],
            rate_info['monthly_payment'],
            customer_data['term_months']
        )
        
        log_request("financial", user_request, "APPROVED", offer['offer_id'])
        
        return {
            "status": "APPROVED",
            "customer": customer_data['name'],
            "offer": offer,
            "rate_info": rate_info
        }
    
    except Exception as e:
        log_request("financial", user_request, "ERROR", str(e))
        return {"status": "ERROR", "reason": f"Financial processing error: {str(e)}"}


# SUPPORT AGENT CODE

def lookup_order(order_id, customer_name):
    
    try:
        response = orders_table.get_item(
            Key={'order_id': order_id}
        )
        
        if 'Item' in response:
            item = response['Item']
            logger.info(f"Order {order_id} found in DynamoDB")
            
            return {
                "order_id": order_id,
                "customer": customer_name,
                "status": item.get('status', 'Unknown'),
                "amount": int(item.get('amount', 0)) if item.get('amount') else 0,
                "order_date": item.get('date', 'N/A'),
                "items": int(item.get('items', 0)) if item.get('items') else 0,
                "tracking_url": f"https://tracking.example.com/{order_id}"
            }
        else:
            logger.info(f"Order {order_id} not found in DynamoDB")
            return {
                "order_id": order_id,
                "customer": customer_name,
                "status": "Not Found",
                "amount": 0
            }
    
    except Exception as e:
        logger.error(f"DynamoDB lookup error for {order_id}: {str(e)}")
        logger.info("Falling back to mock data due to DB error")
        
        mock_orders = {
            "ORD-001": {"status": "Delivered", "amount": 450, "date": "2026-06-20", "items": 2},
            "ORD-002": {"status": "Processing", "amount": 1200, "date": "2026-06-25", "items": 5},
            "ORD-003": {"status": "Shipped", "amount": 850, "date": "2026-06-24", "items": 3},
        }
        
        if order_id in mock_orders:
            order_info = mock_orders[order_id]
            return {
                "order_id": order_id,
                "customer": customer_name,
                "status": order_info["status"],
                "amount": order_info["amount"],
                "order_date": order_info["date"],
                "items": order_info.get("items", 0),
                "tracking_url": f"https://tracking.example.com/{order_id}"
            }
        else:
            return {
                "order_id": order_id,
                "customer": customer_name,
                "status": "Not Found",
                "amount": 0
            }


def process_refund(order_id, amount, reason, order_status):
    
    if order_status == "Not Found":
        return {
            "status": "ERROR",
            "reason": f"Order {order_id} not found in system"
        }
    
    if amount <= 0:
        return {
            "status": "ERROR",
            "reason": f"Cannot process refund for AED {amount}"
        }
    
    refund_id = f"REF-{uuid.uuid4().hex[:8].upper()}"
    
    valid_reasons = ['damaged', 'not_as_described', 'wrong_item', 'changed_mind', 'defective']
    reason_lower = reason.lower().replace(" ", "_")
    
    if reason_lower not in valid_reasons:
        return {
            "refund_id": refund_id,
            "order_id": order_id,
            "amount": amount,
            "reason": reason,
            "status": "PENDING_REVIEW",
            "message": "Refund request submitted for review. We'll contact you within 24 hours.",
            "estimated_processing_days": 5
        }
    
    if amount > 10000:
        return {
            "refund_id": refund_id,
            "order_id": order_id,
            "amount": amount,
            "reason": reason,
            "status": "PENDING_REVIEW",
            "message": "High-value refund request submitted for verification.",
            "estimated_processing_days": 7
        }
    
    try:
        refunds_table.put_item(
            Item={
                'refund_id': refund_id,
                'order_id': order_id,
                'amount': Decimal(str(amount)),
                'reason': reason,
                'status': 'APPROVED',
                'created_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        )
        logger.info(f"Refund {refund_id} stored in DynamoDB")
    except Exception as e:
        logger.warning(f"Could not store refund in DynamoDB: {str(e)}")
    
    return {
        "refund_id": refund_id,
        "order_id": order_id,
        "amount": amount,
        "reason": reason,
        "status": "APPROVED",
        "estimated_processing_days": 3,
        "refund_method": "Original Payment Method",
        "created_date": datetime.datetime.now().strftime("%Y-%m-%d")
    }


def create_support_ticket(issue_type, description, priority, customer_name):
    
    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    try:
        tickets_table.put_item(
            Item={
                'ticket_id': ticket_id,
                'customer': customer_name,
                'issue_type': issue_type,
                'description': description,
                'priority': priority,
                'status': 'OPEN',
                'created_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        )
        logger.info(f"Ticket {ticket_id} stored in DynamoDB")
    except Exception as e:
        logger.warning(f"Could not store ticket in DynamoDB: {str(e)}")
    
    return {
        "ticket_id": ticket_id,
        "customer": customer_name,
        "issue_type": issue_type,
        "description": description,
        "priority": priority,
        "status": "OPEN",
        "assigned_to": "Support Team",
        "created_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "estimated_resolution_hours": 24 if priority == "urgent" else 48
    }


def process_support_request(user_request, groq_api_key):
    
    try:
        client = Groq(api_key=groq_api_key)
        
        extraction_prompt = f"""Extract support request details:

{user_request}

Respond ONLY with JSON:
{{
    "request_type": "order_lookup or refund or complaint or ticket or other",
    "customer_name": "customer name if mentioned",
    "order_id": "order ID if mentioned",
    "issue_description": "description of issue",
    "priority": "low or normal or urgent",
    "issue_type": "damaged, not_as_described, wrong_item, changed_mind, defective, or other"
}}"""
        
        extraction_response = call_groq_with_retry(
            client,
            "llama-3.1-8b-instant",
            [{"role": "user", "content": extraction_prompt}],
            300
        )
        
        response_text = extraction_response.choices[0].message.content
        request_data = extract_json_from_response(response_text)
        
        if not request_data:
            log_request("support", user_request, "ERROR", "Failed to parse support request")
            return {"status": "ERROR", "reason": "Failed to parse support request"}
        
        request_type = request_data.get('request_type', 'other').lower()
        
        if request_type == 'order_lookup':
            order_id = request_data.get('order_id', 'UNKNOWN')
            customer_name = request_data.get('customer_name', 'Valued Customer')
            
            if order_id == 'UNKNOWN':
                log_request("support", user_request, "ERROR", "Order ID not provided")
                return {"status": "ERROR", "reason": "Order ID not provided"}
            
            order_info = lookup_order(order_id, customer_name)
            log_request("support", user_request, "SUCCESS", f"Order lookup {order_id}")
            return {"status": "SUCCESS", "request_type": "order_lookup", "order": order_info}
        
        elif request_type == 'refund':
            order_id = request_data.get('order_id', 'UNKNOWN')
            customer_name = request_data.get('customer_name', 'Valued Customer')
            issue_type = request_data.get('issue_type', 'other')
            
            if order_id == 'UNKNOWN':
                log_request("support", user_request, "ERROR", "Order ID not provided")
                return {"status": "ERROR", "reason": "Order ID not provided"}
            
            order_info = lookup_order(order_id, customer_name)
            amount = order_info.get('amount', 0)
            
            refund = process_refund(order_id, amount, issue_type, order_info['status'])
            
            if refund.get('status') == 'ERROR':
                log_request("support", user_request, "ERROR", refund['reason'])
                return {"status": "ERROR", "reason": refund['reason']}
            
            log_request("support", user_request, "SUCCESS", f"Refund {refund['refund_id']}")
            
            return {
                "status": "SUCCESS",
                "request_type": "refund",
                "refund": refund,
                "message": refund.get('message', f"Your refund of AED {amount} has been processed.")
            }
        
        elif request_type in ['complaint', 'ticket']:
            customer_name = request_data.get('customer_name', 'Valued Customer')
            description = request_data.get('issue_description', 'No description')
            priority = request_data.get('priority', 'normal')
            
            ticket = create_support_ticket(request_type, description, priority, customer_name)
            log_request("support", user_request, "SUCCESS", f"Ticket {ticket['ticket_id']}")
            
            return {
                "status": "SUCCESS",
                "request_type": "ticket",
                "ticket": ticket,
                "message": f"Your {request_type} has been logged as ticket {ticket['ticket_id']}. Resolution time: {ticket['estimated_resolution_hours']} hours."
            }
        
        else:
            customer_name = request_data.get('customer_name', 'Valued Customer')
            description = request_data.get('issue_description', 'General inquiry')
            
            ticket = create_support_ticket('inquiry', description, 'normal', customer_name)
            log_request("support", user_request, "SUCCESS", f"Inquiry {ticket['ticket_id']}")
            
            return {
                "status": "SUCCESS",
                "request_type": "inquiry",
                "ticket": ticket,
                "message": f"Your inquiry has been received as ticket {ticket['ticket_id']}. We'll respond within {ticket['estimated_resolution_hours']} hours."
            }
    
    except Exception as e:
        log_request("support", user_request, "ERROR", str(e))
        return {"status": "ERROR", "reason": f"Support processing error: {str(e)}"}


# LAMBDA HANDLER

def get_cors_headers(origin):
    
    if origin in ALLOWED_ORIGINS:
        return {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }
    else:
        return {
            'Content-Type': 'application/json'
        }

def validate_api_request(event):
    
    groq_api_key = os.environ.get('GROQ_API_KEY')
    if not groq_api_key:
        return False, "Groq API key not configured"
    
    try:
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})
    except json.JSONDecodeError:
        return False, "Invalid JSON in request body"
    
    service_type = body.get('service_type', '').lower().strip()
    if service_type not in ['financial', 'support']:
        return False, f"Unknown service type: {service_type}"
    
    user_request = body.get('request', '').strip()
    if not user_request:
        return False, "No request provided"
    
    if len(user_request) > 5000:
        return False, "Request too long (max 5000 characters)"
    
    return True, groq_api_key


def lambda_handler(event, context):
    
    try:
        import uuid
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        origin = event.get('headers', {}).get('origin', '')
        cors_headers = get_cors_headers(origin)
        
        http_method = event.get('httpMethod') or event.get('requestContext', {}).get('http', {}).get('method', '')
        if event.get('httpMethod') == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': cors_headers,
                'body': ''
            }
        
        is_valid, result = validate_api_request(event)
        if not is_valid:
            logger.warning(f"Invalid request: {result}")
            response_time = int((time.time() - start_time) * 1000)
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({
                    'error': result,
                    'request_id': request_id,
                    'timestamp': datetime.datetime.now().isoformat(),
                    'response_time_ms': response_time
                })
            }
        
        groq_api_key = result
        
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})
        
        service_type = body.get('service_type', 'financial').lower().strip()
        user_request = body.get('request', '').strip()
        
        if service_type == 'financial':
            result = process_financial_request(user_request, groq_api_key)
        elif service_type == 'support':
            result = process_support_request(user_request, groq_api_key)
        
        response_time = int((time.time() - start_time) * 1000)
        result['request_id'] = request_id
        result['timestamp'] = datetime.datetime.now().isoformat()
        result['response_time_ms'] = response_time
        
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps(result)
        }
    
    except Exception as e:
        logger.error(f"Lambda error: {str(e)}")
        response_time = int((time.time() - start_time) * 1000) if 'start_time' in locals() else 0
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': 'Internal server error',
                'response_time_ms': response_time
            })
        }