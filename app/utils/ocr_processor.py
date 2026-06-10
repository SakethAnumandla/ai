# utils/ocr_processor.py
import pytesseract
from PIL import Image
import pdf2image
import cv2
import numpy as np
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
import json
import logging
import os
from io import BytesIO
import base64
from fuzzywuzzy import fuzz, process
import requests
from app.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure tesseract path (adjust based on your OS)
# Windows: pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# Linux: usually in PATH
# Mac: /usr/local/bin/tesseract

class OCRProcessor:
    """Advanced OCR processor for bill extraction"""
    
    def __init__(self, use_cloud_ocr: bool = False, cloud_ocr_api_key: Optional[str] = None):
        """
        Initialize OCR processor
        
        Args:
            use_cloud_ocr: Whether to use cloud-based OCR (Google Vision/AWS Textract)
            cloud_ocr_api_key: API key for cloud OCR service
        """
        self.use_cloud_ocr = use_cloud_ocr
        self.cloud_ocr_api_key = cloud_ocr_api_key or settings.ocr_api_key
        
        # Common patterns for Indian bills
        self.vendor_patterns = {
            'uber': ['uber', 'uber technologies', 'uber ride'],
            'rapido': ['rapido', 'rapido bike taxi', 'rapido auto'],
            'swiggy': ['swiggy', 'swiggy food delivery'],
            'zomato': ['zomato', 'zomato gold', 'zomato pro'],
            'amazon': ['amazon', 'amazon.in', 'amazon pay'],
            'flipkart': ['flipkart', 'flipkart.com'],
            'bigbasket': ['bigbasket', 'bb daily'],
            'blinkit': ['blinkit', 'blinkit delivery'],
            'zepto': ['zepto', 'zepto delivery']
        }
        
        # GST rate patterns
        self.gst_patterns = {
            '5': [5.0],
            '12': [12.0],
            '18': [18.0],
            '28': [28.0]
        }
    
    def preprocess_image(self, image_path: str) -> np.ndarray:
        """
        Preprocess image for better OCR results
        
        Args:
            image_path: Path to image file
            
        Returns:
            Preprocessed image as numpy array
        """
        # Read image
        image = cv2.imread(image_path)
        
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(gray, None, 30, 7, 21)
        
        # Apply threshold to get binary image
        thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        # Deskew image (correct orientation)
        coords = np.column_stack(np.where(thresh > 0))
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
            
        if abs(angle) > 0.5:
            (h, w) = thresh.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            thresh = cv2.warpAffine(thresh, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        
        # Enhance contrast
        enhanced = cv2.convertScaleAbs(thresh, alpha=1.5, beta=0)
        
        return enhanced
    
    def extract_text_with_tesseract(self, image: np.ndarray, lang: str = 'eng') -> str:
        """
        Extract text using Tesseract OCR
        
        Args:
            image: Preprocessed image
            lang: Language code (eng, hin, etc.)
            
        Returns:
            Extracted text
        """
        try:
            # Configure Tesseract parameters
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789₹.,/-: '
            
            text = pytesseract.image_to_string(image, config=custom_config, lang=lang)
            return text
        except Exception as e:
            logger.error(f"Tesseract OCR failed: {str(e)}")
            return ""
    
    async def extract_text_with_cloud_ocr(self, image_path: str) -> str:
        """
        Extract text using cloud-based OCR service
        
        Args:
            image_path: Path to image file
            
        Returns:
            Extracted text
        """
        # This is a placeholder for Google Vision API or AWS Textract
        # Implement based on your chosen service
        
        # Example for Google Vision API:
        # from google.cloud import vision
        # client = vision.ImageAnnotatorClient()
        # with open(image_path, 'rb') as image_file:
        #     content = image_file.read()
        # image = vision.Image(content=content)
        # response = client.text_detection(image=image)
        # texts = response.text_annotations
        # return texts[0].description if texts else ""
        
        # For now, fallback to Tesseract
        image = self.preprocess_image(image_path)
        return self.extract_text_with_tesseract(image)
    
    def extract_bill_number(self, text: str) -> Optional[str]:
        """Extract bill/invoice number from text"""
        patterns = [
            r'(?:Bill|Invoice|Order|Receipt)\s*(?:No|Number|ID|#)[.:\s]*([A-Z0-9][-/\w]{3,20})',
            r'(?:Bill|Invoice|Order)\s*#?\s*[:]?\s*([A-Z0-9][-/\w]{3,20})',
            r'(?:Transaction|Reference)\s*(?:ID|No)[.:\s]*([A-Z0-9]{8,20})',
            r'Order\s*(?:ID|Number)[.:\s]*([A-Z0-9]{5,20})',
            r'([A-Z]{2,4}\d{6,12})'  # Generic pattern for alphanumeric codes
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None
    
    def extract_dates(self, text: str) -> Dict[str, Optional[datetime]]:
        """Extract various dates from bill"""
        dates = {
            'bill_date': None,
            'due_date': None,
            'transaction_date': None
        }
        
        # Date patterns (Indian format: DD/MM/YYYY, DD-MM-YYYY)
        date_patterns = [
            (r'(?:Bill|Invoice|Order)\s*Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', 'bill_date'),
            (r'Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', 'bill_date'),
            (r'Due\s*Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', 'due_date'),
            (r'Transaction\s*Date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', 'transaction_date'),
            (r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})', 'bill_date')  # Fallback
        ]
        
        for pattern, date_type in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    date_str = match.group(1)
                    # Try different date formats
                    for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y']:
                        try:
                            dates[date_type] = datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            continue
                except:
                    continue
        
        return dates
    
    def extract_amounts(self, text: str) -> Dict[str, Optional[float]]:
        """Extract various amounts from bill"""
        amounts = {
            'total': None,
            'subtotal': None,
            'tax': None,
            'discount': None,
            'shipping': None,
            'convenience_fee': None,
            'tip': None,
            'round_off': None
        }
        
        # Common amount patterns
        amount_patterns = [
            (r'(?:Grand\s*Total|Total\s*Amount)[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'total'),
            (r'Total[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'total'),
            (r'Subtotal[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'subtotal'),
            (r'Tax|GST[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'tax'),
            (r'Discount[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'discount'),
            (r'Shipping|Delivery\s*Charge[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'shipping'),
            (r'Convenience\s*Fee[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'convenience_fee'),
            (r'Tip[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'tip'),
            (r'Round\s*Off[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', 'round_off')
        ]
        
        for pattern, amount_type in amount_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount_str = match.group(1).replace(',', '')
                    amounts[amount_type] = float(amount_str)
                except:
                    continue
        
        return amounts
    
    def extract_vendor_info(self, text: str) -> Dict[str, Optional[str]]:
        """Extract vendor information"""
        vendor_info = {
            'name': None,
            'gst': None,
            'address': None,
            'phone': None
        }
        
        # Check for known vendors using fuzzy matching
        text_lower = text.lower()
        for vendor, keywords in self.vendor_patterns.items():
            for keyword in keywords:
                if keyword in text_lower:
                    vendor_info['name'] = vendor.upper()
                    break
            if vendor_info['name']:
                break
        
        # If not found, try to extract from text
        if not vendor_info['name']:
            vendor_patterns = [
                r'(?:Vendor|Seller|Merchant|Store)[:\s]*([A-Za-z\s]+?)(?:\n|$)',
                r'([A-Za-z\s]+(?:Pvt|Limited|LLP|Inc|Corp))',
                r'^([A-Za-z\s]{5,30})$'  # Line that might be vendor name
            ]
            
            for pattern in vendor_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    vendor_info['name'] = match.group(1).strip()
                    break
        
        # Extract GST number
        gst_pattern = r'([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[A-Z0-9]{1})'
        match = re.search(gst_pattern, text)
        if match:
            vendor_info['gst'] = match.group(1)
        
        # Extract phone number
        phone_pattern = r'(?:\+91|0)?\s?[6-9]\d{9}'
        match = re.search(phone_pattern, text)
        if match:
            vendor_info['phone'] = match.group(0)
        
        # Extract address (simplified)
        address_pattern = r'(?:Address|Located at)[:\s]*([^.\n]{20,100})'
        match = re.search(address_pattern, text, re.IGNORECASE)
        if match:
            vendor_info['address'] = match.group(1).strip()
        
        return vendor_info
    
    def extract_ride_details(self, text: str) -> Dict[str, Any]:
        """Extract ride-specific details (Uber, Rapido, Ola)"""
        ride_details = {
            'distance_km': None,
            'duration_min': None,
            'pickup': None,
            'dropoff': None,
            'ride_type': None,
            'vehicle_number': None,
            'driver_name': None
        }
        
        # Distance
        distance_match = re.search(r'(\d+\.?\d*)\s*(?:km|kms|kilometers?)', text, re.IGNORECASE)
        if distance_match:
            ride_details['distance_km'] = float(distance_match.group(1))
        
        # Duration
        duration_match = re.search(r'(\d+)\s*(?:min|mins|minutes?)', text, re.IGNORECASE)
        if duration_match:
            ride_details['duration_min'] = int(duration_match.group(1))
        
        # Pickup location
        pickup_patterns = [
            r'Pickup[:\s]*(.+?)(?=Dropoff|$|\n)',
            r'From[:\s]*(.+?)(?=To|$|\n)'
        ]
        for pattern in pickup_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                ride_details['pickup'] = match.group(1).strip()
                break
        
        # Dropoff location
        dropoff_patterns = [
            r'Dropoff[:\s]*(.+?)(?=Payment|$|\n)',
            r'To[:\s]*(.+?)(?=Payment|$|\n)'
        ]
        for pattern in dropoff_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                ride_details['dropoff'] = match.group(1).strip()
                break
        
        # Ride type
        ride_types = ['UberGo', 'UberXL', 'UberPremier', 'Rapido Auto', 'Rapido Bike', 'Ola Micro', 'Ola Mini']
        for ride_type in ride_types:
            if ride_type.lower() in text.lower():
                ride_details['ride_type'] = ride_type
                break
        
        # Vehicle number
        vehicle_pattern = r'([A-Z]{2}[-\s]?[0-9]{1,2}[-\s]?[A-Z]{1,2}[-\s]?[0-9]{4})'
        match = re.search(vehicle_pattern, text)
        if match:
            ride_details['vehicle_number'] = match.group(1)
        
        return ride_details
    
    def extract_food_details(self, text: str) -> Dict[str, Any]:
        """Extract food delivery details (Swiggy, Zomato)"""
        food_details = {
            'restaurant_name': None,
            'items': [],
            'delivery_charge': None,
            'packaging_charge': None,
            'platform_fee': None
        }
        
        # Restaurant name
        restaurant_patterns = [
            r'From[:\s]*(.+?)(?=Order|$|\n)',
            r'Restaurant[:\s]*(.+?)(?=\n|$)',
            r'([A-Za-z\s]+(?:Kitchen|Restaurant|Cafe|Bistro))'
        ]
        for pattern in restaurant_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                food_details['restaurant_name'] = match.group(1).strip()
                break
        
        # Extract items (quantity, name, price)
        item_patterns = [
            r'(\d+)\s*x\s*(.+?)\s+[₹Rs.]?\s*([\d,]+\.?\d*)',
            r'(.+?)\s+[₹Rs.]?\s*([\d,]+\.?\d*)\s+x\s*(\d+)'
        ]
        
        for pattern in item_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match) == 3:
                    if match[0].isdigit():  # Format: quantity x name price
                        food_details['items'].append({
                            'quantity': int(match[0]),
                            'name': match[1].strip(),
                            'price': float(match[2].replace(',', ''))
                        })
                    else:  # Format: name price x quantity
                        food_details['items'].append({
                            'quantity': int(match[2]),
                            'name': match[0].strip(),
                            'price': float(match[1].replace(',', ''))
                        })
        
        # Delivery charges
        delivery_patterns = [
            r'Delivery\s*Charge[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)',
            r'Delivery\s*Fee[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)'
        ]
        for pattern in delivery_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                food_details['delivery_charge'] = float(match.group(1).replace(',', ''))
                break
        
        # Packaging charge
        packaging_match = re.search(r'Packaging\s*Charge[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
        if packaging_match:
            food_details['packaging_charge'] = float(packaging_match.group(1).replace(',', ''))
        
        # Platform fee
        platform_match = re.search(r'Platform\s*Fee[:\s]*[₹Rs.]?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
        if platform_match:
            food_details['platform_fee'] = float(platform_match.group(1).replace(',', ''))
        
        return food_details
    
    def extract_payment_details(self, text: str) -> Dict[str, Any]:
        """Extract payment-related information"""
        payment_details = {
            'method': None,
            'status': None,
            'transaction_id': None,
            'card_last_four': None,
            'upi_id': None
        }
        
        # Payment method
        payment_methods = ['Credit Card', 'Debit Card', 'UPI', 'Net Banking', 'Cash', 'Wallet', 'Paytm', 'Google Pay']
        for method in payment_methods:
            if method.lower() in text.lower():
                payment_details['method'] = method
                break
        
        # Payment status
        if 'successful' in text.lower() or 'success' in text.lower():
            payment_details['status'] = 'Success'
        elif 'failed' in text.lower() or 'declined' in text.lower():
            payment_details['status'] = 'Failed'
        elif 'pending' in text.lower():
            payment_details['status'] = 'Pending'
        
        # Transaction ID
        txn_patterns = [
            r'(?:Transaction|Txn|Payment)\s*(?:ID|No|#)[:\s]*([A-Z0-9]{10,20})',
            r'([A-Z0-9]{12,20})'
        ]
        for pattern in txn_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                payment_details['transaction_id'] = match.group(1)
                break
        
        # Card last 4 digits
        card_match = re.search(r'Card[:\s]*xxxx[-\s]*(\d{4})', text, re.IGNORECASE)
        if card_match:
            payment_details['card_last_four'] = card_match.group(1)
        
        # UPI ID
        upi_match = re.search(r'([a-zA-Z0-9.-]+@[a-zA-Z]+)', text)
        if upi_match:
            payment_details['upi_id'] = upi_match.group(1)
        
        return payment_details
    
    def calculate_confidence_score(self, extracted_data: Dict[str, Any]) -> float:
        """Calculate confidence score based on extracted fields"""
        score = 0.0
        total_fields = 0
        
        # Check critical fields
        critical_fields = ['total_amount', 'bill_date', 'vendor_name']
        for field in critical_fields:
            total_fields += 1
            if extracted_data.get(field):
                score += 1
        
        # Check other important fields
        important_fields = ['bill_number', 'tax_amount', 'payment_method']
        for field in important_fields:
            total_fields += 0.5
            if extracted_data.get(field):
                score += 0.5
        
        # Calculate percentage
        confidence = (score / total_fields) * 100 if total_fields > 0 else 0
        
        return min(confidence, 100.0)
    
    async def process_bill(self, file_path: str, file_type: str) -> Dict[str, Any]:
        """
        Main method to process bill and extract all information
        
        Args:
            file_path: Path to the bill file
            file_type: Type of file (pdf, jpg, png, etc.)
            
        Returns:
            Dictionary with all extracted information
        """
        try:
            # Extract text based on file type
            if file_type.lower() == 'pdf':
                # Convert PDF to images
                images = pdf2image.convert_from_path(file_path, first_page=1, last_page=1)
                if images:
                    # Save first page as temp image
                    temp_image = BytesIO()
                    images[0].save(temp_image, format='JPEG')
                    temp_image.seek(0)
                    
                    # Preprocess and extract text
                    img_array = np.array(images[0])
                    preprocessed = self.preprocess_image_from_array(img_array)
                    text = self.extract_text_with_tesseract(preprocessed)
                else:
                    text = ""
            else:
                # Process image
                preprocessed = self.preprocess_image(file_path)
                if self.use_cloud_ocr:
                    text = await self.extract_text_with_cloud_ocr(file_path)
                else:
                    text = self.extract_text_with_tesseract(preprocessed)
            
            if not text:
                logger.warning(f"No text extracted from {file_path}")
                return {'error': 'No text could be extracted from the bill'}
            
            logger.info(f"Extracted text length: {len(text)} characters")
            
            # Extract all information
            extracted_data = {
                'bill_number': self.extract_bill_number(text),
                'dates': self.extract_dates(text),
                'amounts': self.extract_amounts(text),
                'vendor': self.extract_vendor_info(text),
                'ride_details': self.extract_ride_details(text),
                'food_details': self.extract_food_details(text),
                'payment_details': self.extract_payment_details(text),
                'raw_text': text[:5000],  # Store first 5000 chars
                'full_text': text  # Store full text for debugging
            }
            
            # Flatten the data for database storage
            flattened_data = {
                'bill_number': extracted_data['bill_number'],
                'bill_date': extracted_data['dates'].get('bill_date'),
                'due_date': extracted_data['dates'].get('due_date'),
                'vendor_name': extracted_data['vendor'].get('name'),
                'vendor_gst': extracted_data['vendor'].get('gst'),
                'vendor_address': extracted_data['vendor'].get('address'),
                'total_amount': extracted_data['amounts'].get('total'),
                'subtotal': extracted_data['amounts'].get('subtotal'),
                'tax_amount': extracted_data['amounts'].get('tax'),
                'discount_amount': extracted_data['amounts'].get('discount'),
                'shipping_charges': extracted_data['amounts'].get('shipping'),
                'convenience_fee': extracted_data['amounts'].get('convenience_fee'),
                'tip_amount': extracted_data['amounts'].get('tip'),
                'round_off': extracted_data['amounts'].get('round_off'),
                'ride_distance': extracted_data['ride_details'].get('distance_km'),
                'ride_duration': extracted_data['ride_details'].get('duration_min'),
                'pickup_location': extracted_data['ride_details'].get('pickup'),
                'dropoff_location': extracted_data['ride_details'].get('dropoff'),
                'ride_type': extracted_data['ride_details'].get('ride_type'),
                'vehicle_number': extracted_data['ride_details'].get('vehicle_number'),
                'driver_name': extracted_data['ride_details'].get('driver_name'),
                'restaurant_name': extracted_data['food_details'].get('restaurant_name'),
                'items_list': extracted_data['food_details'].get('items'),
                'delivery_charge': extracted_data['food_details'].get('delivery_charge'),
                'packaging_charge': extracted_data['food_details'].get('packaging_charge'),
                'platform_fee': extracted_data['food_details'].get('platform_fee'),
                'payment_method': extracted_data['payment_details'].get('method'),
                'payment_status': extracted_data['payment_details'].get('status'),
                'payment_transaction_id': extracted_data['payment_details'].get('transaction_id'),
                'card_last_four': extracted_data['payment_details'].get('card_last_four'),
                'raw_text': extracted_data['raw_text'],
                'extracted_fields': {
                    'dates': extracted_data['dates'],
                    'amounts': extracted_data['amounts'],
                    'vendor': extracted_data['vendor'],
                    'ride_details': extracted_data['ride_details'],
                    'food_details': extracted_data['food_details'],
                    'payment_details': extracted_data['payment_details']
                }
            }
            
            # Calculate confidence score
            flattened_data['confidence_score'] = self.calculate_confidence_score(flattened_data)
            
            # Determine category based on vendor
            category = self.determine_category(flattened_data)
            flattened_data['suggested_category'] = category
            
            return flattened_data
            
        except Exception as e:
            logger.error(f"OCR processing failed: {str(e)}", exc_info=True)
            return {'error': f'OCR processing failed: {str(e)}'}
    
    def preprocess_image_from_array(self, image_array: np.ndarray) -> np.ndarray:
        """Preprocess image from numpy array"""
        # Convert to grayscale if needed
        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = image_array
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(gray, None, 30, 7, 21)
        
        # Threshold
        thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        return thresh
    
    def determine_category(self, data: Dict[str, Any]) -> str:
        """Determine expense category based on extracted data"""
        vendor_name = str(data.get('vendor_name', '')).lower()
        restaurant_name = str(data.get('restaurant_name', '')).lower()
        
        # Check for ride services
        if any(ride in vendor_name for ride in ['uber', 'rapido', 'ola']):
            return 'travel'
        
        # Check for food delivery
        if any(food in vendor_name or food in restaurant_name 
               for food in ['swiggy', 'zomato', 'restaurant', 'cafe', 'kitchen']):
            return 'food'
        
        # Check for fuel
        if 'fuel' in vendor_name or 'petrol' in vendor_name:
            return 'fuel'
        
        # Check for shopping
        if any(shop in vendor_name for shop in ['amazon', 'flipkart', 'myntra']):
            return 'shopping'
        
        # Default category
        return 'other'

async def process_bill_with_ocr(file_path: str, file_type: str) -> Dict[str, Any]:
    """
    Convenience function to process bill with OCR
    
    Args:
        file_path: Path to bill file
        file_type: Type of file
        
    Returns:
        Extracted bill data
    """
    processor = OCRProcessor()
    return await processor.process_bill(file_path, file_type)