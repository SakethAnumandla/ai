# utils/validators.py
import re
from datetime import datetime
from typing import Optional, List, Tuple
from email_validator import validate_email as validate_email_lib, EmailNotValidError
import phonenumbers
from fastapi import HTTPException, status

# Email validation
def validate_email(email: str) -> bool:
    """
    Validate email address format
    
    Args:
        email: Email address to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        validate_email_lib(email)
        return True
    except EmailNotValidError:
        return False

# Amount validation
def validate_amount(amount: float, min_amount: float = 0.01, max_amount: float = 1_000_000) -> Tuple[bool, Optional[str]]:
    """
    Validate amount value
    
    Args:
        amount: Amount to validate
        min_amount: Minimum allowed amount
        max_amount: Maximum allowed amount
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if amount <= 0:
        return False, "Amount must be greater than 0"
    
    if amount < min_amount:
        return False, f"Amount must be at least {min_amount}"
    
    if amount > max_amount:
        return False, f"Amount cannot exceed {max_amount}"
    
    # Check for decimal places (max 2)
    if len(str(amount).split('.')[-1]) > 2:
        return False, "Amount can have at most 2 decimal places"
    
    return True, None

# Date validation
def validate_date(date_str: str, date_format: str = "%Y-%m-%d") -> Tuple[bool, Optional[datetime], Optional[str]]:
    """
    Validate date string
    
    Args:
        date_str: Date string to validate
        date_format: Expected date format
        
    Returns:
        Tuple of (is_valid, datetime_object, error_message)
    """
    try:
        parsed_date = datetime.strptime(date_str, date_format)
        
        # Check if date is not in future (allow current date)
        if parsed_date > datetime.now():
            return False, None, "Date cannot be in the future"
        
        # Check if date is not too old (e.g., before year 2000)
        if parsed_date.year < 2000:
            return False, None, "Date is too old (year must be >= 2000)"
        
        return True, parsed_date, None
        
    except ValueError:
        return False, None, f"Invalid date format. Expected {date_format}"

# File type validation
def validate_file_type(filename: str, allowed_extensions: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate file type based on extension
    
    Args:
        filename: Name of the file
        allowed_extensions: List of allowed extensions
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not filename:
        return False, "No filename provided"
    
    extension = filename.split('.')[-1].lower() if '.' in filename else ''
    
    if not extension:
        return False, "File has no extension"
    
    if extension not in allowed_extensions:
        return False, f"File type '{extension}' not allowed. Allowed: {', '.join(allowed_extensions)}"
    
    return True, None

# Bill number validation
def validate_bill_number(bill_number: str) -> Tuple[bool, Optional[str]]:
    """
    Validate bill/invoice number format
    
    Args:
        bill_number: Bill number to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not bill_number:
        return True, None  # Bill number is optional
    
    # Check length
    if len(bill_number) < 3:
        return False, "Bill number too short (minimum 3 characters)"
    
    if len(bill_number) > 50:
        return False, "Bill number too long (maximum 50 characters)"
    
    # Check for allowed characters (alphanumeric, dash, underscore, slash)
    if not re.match(r'^[A-Za-z0-9\-_/]+$', bill_number):
        return False, "Bill number contains invalid characters"
    
    return True, None

# Phone number validation (Indian numbers)
def validate_phone_number(phone_number: str, country: str = "IN") -> Tuple[bool, Optional[str]]:
    """
    Validate phone number
    
    Args:
        phone_number: Phone number to validate
        country: Country code (default: IN for India)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        parsed_number = phonenumbers.parse(phone_number, country)
        
        if not phonenumbers.is_valid_number(parsed_number):
            return False, "Invalid phone number format"
        
        return True, None
        
    except phonenumbers.NumberParseException:
        return False, "Could not parse phone number"

# PAN card validation (Indian)
def validate_pan_number(pan_number: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Indian PAN card number
    
    Args:
        pan_number: PAN number to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not pan_number:
        return True, None  # PAN is optional
    
    # PAN format: 5 letters, 4 digits, 1 letter
    pattern = r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
    
    if not re.match(pattern, pan_number.upper()):
        return False, "Invalid PAN number format. Expected: ABCDE1234F"
    
    return True, None

# GST validation (Indian)
def validate_gst_number(gst_number: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Indian GST number
    
    Args:
        gst_number: GST number to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not gst_number:
        return True, None  # GST is optional
    
    # GST format: 15 characters
    # 2 digits state code, 10 digits PAN, 1 digit entity code, 1 digit check sum, 1 digit zone code
    pattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[A-Z0-9]{1}$'
    
    if not re.match(pattern, gst_number.upper()):
        return False, "Invalid GST number format"
    
    return True, None

# Input sanitization
def sanitize_input(text: str, max_length: int = 500) -> str:
    """
    Sanitize user input to prevent XSS and SQL injection
    
    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length
        
    Returns:
        Sanitized text
    """
    if not text:
        return ""
    
    # Trim whitespace
    text = text.strip()
    
    # Limit length
    if len(text) > max_length:
        text = text[:max_length]
    
    # Remove potentially dangerous characters
    # This is basic - for production, use a proper sanitization library
    dangerous_chars = ['<', '>', '&', '%', '$', '#', '@', '!', '`', ';', "'", '"']
    for char in dangerous_chars:
        text = text.replace(char, '')
    
    return text

# Category validation
def validate_category(category: str, valid_categories: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate expense category
    
    Args:
        category: Category to validate
        valid_categories: List of valid category names
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not category:
        return False, "Category is required"
    
    category_lower = category.lower()
    valid_lower = [cat.lower() for cat in valid_categories]
    
    if category_lower not in valid_lower:
        return False, f"Invalid category. Valid categories: {', '.join(valid_categories)}"
    
    return True, None

# Status validation
def validate_status(status: str, valid_statuses: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate expense status
    
    Args:
        status: Status to validate
        valid_statuses: List of valid status values
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    status_lower = status.lower()
    valid_lower = [s.lower() for s in valid_statuses]
    
    if status_lower not in valid_lower:
        return False, f"Invalid status. Valid statuses: {', '.join(valid_statuses)}"
    
    return True, None

# Transaction type validation
def validate_transaction_type(transaction_type: str) -> Tuple[bool, Optional[str]]:
    """
    Validate transaction type
    
    Args:
        transaction_type: Transaction type to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    valid_types = ['income', 'expense']
    
    if transaction_type.lower() not in valid_types:
        return False, f"Invalid transaction type. Must be one of: {', '.join(valid_types)}"
    
    return True, None

# UPI ID validation
def validate_upi_id(upi_id: str) -> Tuple[bool, Optional[str]]:
    """
    Validate UPI ID format
    
    Args:
        upi_id: UPI ID to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not upi_id:
        return True, None  # UPI ID is optional
    
    # UPI format: username@handle
    pattern = r'^[a-zA-Z0-9.\-_]{2,50}@[a-zA-Z]{3,20}$'
    
    if not re.match(pattern, upi_id):
        return False, "Invalid UPI ID format. Expected: username@bankhandle"
    
    return True, None

# Credit card number validation (Luhn algorithm)
def validate_credit_card(card_number: str) -> Tuple[bool, Optional[str]]:
    """
    Validate credit card number using Luhn algorithm
    
    Args:
        card_number: Credit card number to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not card_number:
        return True, None  # Card number is optional
    
    # Remove spaces and dashes
    card_number = re.sub(r'[\s-]', '', card_number)
    
    # Check if all digits
    if not card_number.isdigit():
        return False, "Card number must contain only digits"
    
    # Check length (most cards are 16 digits)
    if len(card_number) not in [15, 16]:
        return False, "Invalid card number length"
    
    # Luhn algorithm
    def luhn_check(card_num):
        total = 0
        reverse_digits = card_num[::-1]
        
        for i, digit in enumerate(reverse_digits):
            n = int(digit)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n = n % 10 + n // 10
            total += n
        
        return total % 10 == 0
    
    if not luhn_check(card_number):
        return False, "Invalid card number"
    
    return True, None

# IFSC code validation (Indian)
def validate_ifsc_code(ifsc_code: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Indian IFSC code
    
    Args:
        ifsc_code: IFSC code to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not ifsc_code:
        return True, None  # IFSC is optional
    
    # IFSC format: 4 letters, 1 digit/letter, 6 digits/letters
    pattern = r'^[A-Z]{4}[0-9A-Z]{7}$'
    
    if not re.match(pattern, ifsc_code.upper()):
        return False, "Invalid IFSC code format. Expected: ABCD0123456"
    
    return True, None

# Pincode validation (Indian)
def validate_pincode(pincode: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Indian pincode
    
    Args:
        pincode: Pincode to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not pincode:
        return True, None  # Pincode is optional
    
    pincode_str = str(pincode).strip()
    
    # Check if 6 digits
    if not pincode_str.isdigit():
        return False, "Pincode must contain only digits"
    
    if len(pincode_str) != 6:
        return False, "Pincode must be 6 digits"
    
    return True, None

# URL validation
def validate_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate URL format
    
    Args:
        url: URL to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url:
        return True, None  # URL is optional
    
    # Basic URL pattern
    pattern = r'^https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&\/=]*)$'
    
    if not re.match(pattern, url):
        return False, "Invalid URL format"
    
    return True, None

# Combined validator for expense creation
def validate_expense_data(
    amount: float,
    date_str: str,
    category: str,
    transaction_type: str,
    bill_number: Optional[str] = None
) -> List[str]:
    """
    Validate all expense data together
    
    Args:
        amount: Expense amount
        date_str: Expense date
        category: Expense category
        transaction_type: Type of transaction
        bill_number: Optional bill number
        
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Validate amount
    is_valid, error = validate_amount(amount)
    if not is_valid:
        errors.append(error)
    
    # Validate date
    is_valid, _, error = validate_date(date_str)
    if not is_valid:
        errors.append(error)
    
    # Validate category
    valid_categories = ['fuel', 'travel', 'food', 'shopping', 'entertainment', 
                       'bills', 'healthcare', 'education', 'other']
    is_valid, error = validate_category(category, valid_categories)
    if not is_valid:
        errors.append(error)
    
    # Validate transaction type
    is_valid, error = validate_transaction_type(transaction_type)
    if not is_valid:
        errors.append(error)
    
    # Validate bill number if provided
    if bill_number:
        is_valid, error = validate_bill_number(bill_number)
        if not is_valid:
            errors.append(error)
    
    return errors