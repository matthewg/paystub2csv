import pdfplumber
import sys
import csv
import re
from datetime import datetime
import unicodedata

def extract_paystub_data(pdf_path):
    data = {'Earnings': {}, 'Deductions': {}, 'Taxes': {}}
    pay_date = "01/01/1970"
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Extract standard text to reliably find the Pay Date
            text_std = page.extract_text()
            if not text_std:
                continue
            date_match = re.search(r'Pay Date[\s\|]*(\d{2}/\d{2}/\d{4})', text_std)
            if date_match:
                pay_date = date_match.group(1)
                
            # Extract layout text: preserves physical gaps by padding with spaces
            layout_text = page.extract_text(layout=True)
            if not layout_text:
                continue
                
            lines = layout_text.split('\n')
            max_len = max((len(l) for l in lines), default=0)
            
            # Start in the top half (Earnings left, Deductions right)
            mode = 'top' 
            
            for line in lines:
                stripped_lower = line.strip().lower().replace(' ', '')
                if stripped_lower == 'taxes':
                    mode = 'taxes'
                elif stripped_lower in ['paidtimeoff', 'paysummary']:
                    mode = 'done'
                    
                if mode == 'done':
                    break
                    
                if mode == 'top':
                    # Pad line to max width and slice exactly down the middle gap
                    padded_line = line.ljust(max_len)
                    mid = max_len // 2
                    left_part = padded_line[:mid]
                    right_part = padded_line[mid:]
                    
                    parse_line(left_part, 'Earnings', data)
                    parse_line(right_part, 'Deductions', data)
                    
                elif mode == 'taxes':
                    parse_line(line, 'Taxes', data)
                    
    return pay_date, data

def parse_line(text, section, data):
    text = text.strip()
    if not text: return
    
    # Extract all numbers that follow monetary or hours formats
    amounts = re.findall(r'-?\$?[0-9,]+\.\d{2,6}', text)
    if not amounts: return
    
    # The name is defined as everything up to the first amount
    first_amt = amounts[0]
    idx = text.find(first_amt)
    if idx <= 0: return
    
    name = text[:idx].strip()
    
    # Filter out table headers and summary totals
    skip = ['pay type', 'deduction', 'tax', 'total', 'total hours', 'total hours worked', 
            'current', 'ytd', 'gross', 'net pay', 'plan', 'vacation', 'based on', 'balance']
    if not name or name.lower() in skip or name.lower().startswith('total'):
        return
        
    try:
        # Determine the YTD amount
        if section == 'Deductions' and len(amounts) >= 2:
            # For deductions, Employee YTD is always the second monetary column
            ytd_str = amounts[1]
        else:
            # For Earnings and Taxes, YTD is always the final column
            ytd_str = amounts[-1]
            
        ytd = float(re.sub(r'[^\d\.\-]', '', ytd_str))
        
        # Aggressive normalization for dictionary keys to combat PDF spacing/OCR changes
        key = name.replace('Ε', 'E').replace('ε', 'e') # Catch Greek Epsilons
        key = unicodedata.normalize('NFKD', key).encode('ASCII', 'ignore').decode('utf-8')
        key = re.sub(r'[^a-z0-9]', '', key.lower())
        
        # Save both the clean YTD float and the original display name
        data[section][key] = {'name': name, 'ytd': ytd}
    except Exception:
        pass

def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_paystubs.py <new_paystub.pdf> [old_paystub.pdf]")
        sys.exit(1)
        
    new_pdf = sys.argv[1]
    old_pdf = sys.argv[2] if len(sys.argv) > 2 else None
    
    new_date, new_data = extract_paystub_data(new_pdf)
    
    is_january = False
    try:
        if datetime.strptime(new_date, "%m/%d/%Y").month == 1:
            is_january = True
    except ValueError:
        pass
        
    old_data = {'Earnings': {}, 'Deductions': {}, 'Taxes': {}}
    if not is_january and old_pdf:
        _, old_data = extract_paystub_data(old_pdf)
        
    writer = csv.writer(sys.stdout)
    writer.writerow(["Date", "Description", "Amount"])
    
    for category in ['Earnings', 'Deductions', 'Taxes']:
        all_keys = set(new_data[category].keys()).union(set(old_data[category].keys()))
        
        # Retrieve the original display name, prioritizing the newer paystub's formatting
        def get_name(k):
            if k in new_data[category]: return new_data[category][k]['name']
            return old_data[category][k]['name']
            
        for key in sorted(all_keys, key=lambda k: get_name(k).lower()):
            display_name = get_name(key)
            new_ytd = new_data[category].get(key, {}).get('ytd', 0.0)
            old_ytd = old_data[category].get(key, {}).get('ytd', 0.0)
            
            delta = new_ytd if is_january else new_ytd - old_ytd
            
            # Skip line items with zero net change for the month
            if abs(delta) < 0.01:
                continue
                
            # Output Deductions and Taxes as negative sums
            if category in ['Deductions', 'Taxes']:
                delta = -delta
                
            writer.writerow([new_date, f"{category}: {display_name}", f"{delta:.2f}"])

if __name__ == '__main__':
    main()
