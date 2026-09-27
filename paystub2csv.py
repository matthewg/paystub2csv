import pdfplumber
import sys
import csv
import re
from datetime import datetime

def extract_paystub_data(pdf_path):
    data = {'Earnings': {}, 'Deductions': {}, 'Taxes': {}}
    pay_date = "01/01/1970"
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Extract Pay Date from the page text
            text = page.extract_text()
            date_match = re.search(r'Pay Date[\s\|]*(\d{2}/\d{2}/\d{4})', text)
            if date_match:
                pay_date = date_match.group(1)
                
            # Extract spatial words to map the 2D layout
            words = page.extract_words(keep_blank_chars=True)
            
            # Identify the Y-coordinates for the start of each section
            earnings_top = None
            deductions_top = None
            taxes_top = None
            
            for w in words:
                t = w['text'].lower()
                if t == 'earnings' and earnings_top is None:
                    earnings_top = w['top']
                elif t == 'deductions' and deductions_top is None:
                    deductions_top = w['top']
                elif t == 'taxes' and taxes_top is None:
                    taxes_top = w['top']
                    
            if earnings_top is None:
                continue  # Skip pages without paystub tables
                
            taxes_top = taxes_top or page.height
            center_x = page.width / 2
            
            # Find the bottom boundary to exclude Paid Time Off and Pay Summary
            cutoff_top = page.height
            for w in words:
                t = w['text'].lower()
                if t in ['paid time off', 'pay summary'] and w['top'] < cutoff_top:
                    cutoff_top = w['top']
            
            # Route words into their respective tables based on X/Y coordinates
            earnings_words = []
            deductions_words = []
            taxes_words = []
            
            for w in words:
                if w['top'] <= max(earnings_top, deductions_top) + 15:
                    continue  # Ignore main headers
                    
                if w['top'] < taxes_top - 10:
                    if w['x0'] < center_x:
                        earnings_words.append(w)
                    else:
                        deductions_words.append(w)
                elif taxes_top + 10 <= w['top'] < cutoff_top - 5:
                    taxes_words.append(w)
                    
            def parse_section(section_words, section_name):
                # Group words into horizontal lines (using a 3-point vertical bucket)
                lines = {}
                for w in section_words:
                    line_y = round(w['top'] / 3) * 3
                    if line_y not in lines:
                        lines[line_y] = []
                    lines[line_y].append(w)
                    
                for line_y in sorted(lines.keys()):
                    line_words = sorted(lines[line_y], key=lambda w: w['x0'])
                    line_text = " ".join([w['text'] for w in line_words])
                    
                    # Capture everything before the first number or dollar sign
                    name_match = re.match(r'^([^0-9\$]+)', line_text)
                    if not name_match:
                        continue
                        
                    name = name_match.group(1).replace('|', '').strip()
                    if name.lower() in ['pay type', 'deduction', 'tax', 'total hours', 'total hours worked']:
                        continue
                        
                    # Extract all currency amounts strictly ending with 2 decimal places
                    # This safely ignores 4-decimal pay rates and 6-decimal hours
                    amounts = re.findall(r'(-?[0-9,]+\.\d{2})(?!\d)', line_text)
                    
                    if amounts:
                        if section_name == 'Deductions' and len(amounts) >= 2:
                            # Left-to-right deductions format: Emp Current, Emp YTD, ER Current, ER YTD
                            ytd = float(amounts[1].replace(',', ''))
                        else:
                            # Earnings & Taxes consistently have YTD as the final column
                            ytd = float(amounts[-1].replace(',', ''))
                            
                        data[section_name][name] = ytd

            parse_section(earnings_words, 'Earnings')
            parse_section(deductions_words, 'Deductions')
            parse_section(taxes_words, 'Taxes')
            
    return pay_date, data

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
        all_items = set(new_data[category].keys()).union(set(old_data[category].keys()))
        for item in sorted(all_items):
            new_ytd = new_data[category].get(item, 0.0)
            old_ytd = old_data[category].get(item, 0.0)
            
            delta = new_ytd if is_january else new_ytd - old_ytd
            
            # Exclude items with $0.00 delta for the month
            if abs(delta) < 0.01:
                continue
                
            # Report taxes and deductions as negative sums
            if category in ['Deductions', 'Taxes']:
                delta = -delta
                
            writer.writerow([new_date, f"{category}: {item}", f"{delta:.2f}"])

if __name__ == '__main__':
    main()
