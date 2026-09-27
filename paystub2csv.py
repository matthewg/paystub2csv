import csv
import sys
import re
from datetime import datetime

try:
    import pypdf
except ImportError:
    print("Error: The 'pypdf' library is required. Install it using: pip install pypdf")
    sys.exit(1)

def extract_text_from_pdf(pdf_path):
    """Extracts text from a given PDF file."""
    reader = pypdf.PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def parse_paystub(text):
    """
    Parses the extracted PDF text to locate the Pay Date and YTD values 
    for Earnings, Deductions, and Taxes.
    """
    data = {'Earnings': {}, 'Deductions': {}, 'Taxes': {}}
    
    # Extract the Pay Date
    date_match = re.search(r'Pay Date[\s\|]*(\d{2}/\d{2}/\d{4})', text)
    pay_date = date_match.group(1) if date_match else "01/01/1970"
    
    current_section = None
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Identify the current section of the paystub
        if 'Earnings' in line and 'Pay Type' not in line:
            current_section = 'Earnings'
            continue
        elif 'Deductions' in line and 'Deduction' not in line:
            current_section = 'Deductions'
            continue
        elif 'Taxes' in line and 'Tax' not in line and 'Taxable Wages' not in line:
            current_section = 'Taxes'
            continue
        elif 'Paid Time Off' in line or 'Pay Summary' in line:
            current_section = None
            
        if not current_section:
            continue
            
        # Match line items by capturing the name and looking for monetary amounts
        name_match = re.match(r'^([A-Za-z0-9 \-]+?)(?:\s*\||\s{2,}|\s+\d)', line)
        if name_match:
            item_name = name_match.group(1).strip()
            
            # Filter out header rows that might get accidentally matched
            if item_name.lower() in ['pay type', 'deduction', 'tax', 'total hours', 'total', 'based on']:
                continue
                
            # Extract all currency values on the line (e.g., $1,234.56 or 1,234.56$)
            amounts = re.findall(r'[\$]?\s*([0-9,]+\.\d{2})\s*[\$]?', line)
            
            if amounts:
                if current_section == 'Deductions' and len(amounts) >= 2:
                    # PDF extraction sometimes swaps "Employee Current" and "Employee YTD" order.
                    # Because YTD >= Current, the maximum of the first two amounts is the YTD value.
                    val1 = float(amounts[0].replace(',', ''))
                    val2 = float(amounts[1].replace(',', ''))
                    ytd_float = max(val1, val2)
                else:
                    # For Earnings and Taxes, the YTD value is reliably the final amount on the line.
                    ytd_float = float(amounts[-1].replace(',', ''))
                    
                data[current_section][item_name] = ytd_float

    return pay_date, data

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <new_paystub.pdf> [old_paystub.pdf]")
        sys.exit(1)
        
    new_pdf = sys.argv[1]
    old_pdf = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Parse the current month's paystub
    new_text = extract_text_from_pdf(new_pdf)
    new_date, new_data = parse_paystub(new_text)
    
    # Determine if it is a January paystub
    is_january = False
    try:
        date_obj = datetime.strptime(new_date, "%m/%d/%Y")
        if date_obj.month == 1:
            is_january = True
    except ValueError:
        pass
        
    # Parse the previous month's paystub if it is not January
    old_data = {'Earnings': {}, 'Deductions': {}, 'Taxes': {}}
    if not is_january and old_pdf:
        old_text = extract_text_from_pdf(old_pdf)
        _, old_data = parse_paystub(old_text)
        
    # Generate the CSV output to stdout
    writer = csv.writer(sys.stdout)
    writer.writerow(["Date", "Description", "Amount"])
    
    for category in ['Earnings', 'Deductions', 'Taxes']:
        # Combine unique line items from both paystubs to catch new or dropped items
        all_items = set(new_data[category].keys()).union(set(old_data[category].keys()))
        
        for item in sorted(all_items):
            new_ytd = new_data[category].get(item, 0.0)
            old_ytd = old_data[category].get(item, 0.0)
            
            # Calculate the delta based on whether it is the start of the year
            if is_january:
                delta = new_ytd
            else:
                delta = new_ytd - old_ytd
                
            # Exclude items with zero activity for the month
            if delta == 0:
                continue
                
            # Apply appropriate negative/positive signs based on the category
            if category in ['Deductions', 'Taxes']:
                delta = -delta
                
            description = f"{category}: {item}"
            writer.writerow([new_date, description, f"{delta:.2f}"])

if __name__ == '__main__':
    main()
