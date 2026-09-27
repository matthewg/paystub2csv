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
            text_std = page.extract_text()
            if not text_std:
                continue
                
            # Extract standard text to reliably find the Pay Date
            date_match = re.search(r'Pay Date[\s\|]*(\d{2}/\d{2}/\d{4})', text_std)
            if date_match:
                pay_date = date_match.group(1)
                
            words = page.extract_words()
            if not words:
                continue
                
            # Locate the X, Y coordinates of the table headers to define our crop boundaries
            e_top, d_top, d_x0, t_top = None, None, None, None
            
            for w in words:
                t = w['text'].lower()
                if t == 'earnings' and e_top is None and w['top'] < page.height * 0.5:
                    e_top = w['top']
                if t == 'deductions' and d_top is None and w['top'] < page.height * 0.5:
                    d_top = w['top']
                    d_x0 = w['x0']  # The exact X-coordinate where the Deductions table begins
                if t == 'taxes' and t_top is None and w['top'] > page.height * 0.3:
                    t_top = w['top']
                    
            # Locate the Y-coordinate of the bottom cutoff (to exclude Paid Time Off)
            cutoff_top = page.height
            for i, w in enumerate(words):
                t = w['text'].lower()
                if t == 'paid' and i + 1 < len(words) and 'time' in words[i+1]['text'].lower():
                    if t_top is None or w['top'] > t_top:
                        cutoff_top = min(cutoff_top, w['top'])
                if t == 'pay' and i + 1 < len(words) and 'summary' in words[i+1]['text'].lower():
                    if t_top is None or w['top'] > t_top:
                        cutoff_top = min(cutoff_top, w['top'])

            # Apply defaults if any headers were missing on the page
            e_top = e_top if e_top is not None else 0
            d_top = d_top if d_top is not None else 0
            d_x0 = d_x0 if d_x0 is not None else (page.width / 2)
            t_top = t_top if t_top is not None else cutoff_top
            
            e_bottom = min(t_top, cutoff_top)
            d_bottom = min(t_top, cutoff_top)
            t_bottom = cutoff_top
            
            # Helper to crop the page and extract text only within that physical box
            def get_bbox_text(x0, top, x1, bottom):
                if top >= bottom or x0 >= x1:
                    return ""
                try:
                    return page.within_bbox((x0, top, x1, bottom)).extract_text(layout=True)
                except Exception:
                    return ""

            # Mathematically isolate the 3 sections to prevent column-bleeding
            e_text = get_bbox_text(0, e_top, d_x0 - 5, e_bottom)
            d_text = get_bbox_text(d_x0 - 5, d_top, page.width, d_bottom)
            t_text = get_bbox_text(0, t_top, page.width, t_bottom) if t_top < cutoff_top else ""
            
            def parse_section(text, section_name):
                if not text: return
                for line in text.split('\n'):
                    line = line.strip()
                    if not line: continue
                    
                    # Match all monetary amounts/hours that include decimals
                    matches = list(re.finditer(r'[-\$]{0,2}[0-9,]+\.\d+', line))
                    if not matches:
                        continue
                        
                    first_match_start = matches[0].start()
                    name = line[:first_match_start].strip()
                    
                    # Strip all spaces and punctuation from the name so it strictly matches across months
                    name_clean = re.sub(r'[^a-z0-9]', '', name.lower())
                    
                    skip = ['paytype', 'deduction', 'tax', 'total', 'totalhours', 'totalhoursworked', 
                            'current', 'ytd', 'gross', 'netpay', 'plan', 'vacation', 'basedon', 'balance', 
                            'employeecurrent', 'employercurrent', 'employeeytd', 'employerytd']
                            
                    if not name_clean or name_clean in skip or name.lower().startswith('total'):
                        continue
                        
                    amounts_str = [m.group() for m in matches]
                    amounts = [float(re.sub(r'[^\d\.\-]', '', a)) for a in amounts_str]
                    
                    try:
                        # Grab appropriate YTD amount based on table structure
                        if section_name == 'Deductions' and len(amounts) >= 2:
                            ytd = amounts[1]
                        else:
                            ytd = amounts[-1]
                            
                        data[section_name][name_clean] = {'name': name, 'ytd': ytd}
                    except IndexError:
                        pass

            parse_section(e_text, 'Earnings')
            parse_section(d_text, 'Deductions')
            parse_section(t_text, 'Taxes')
            
    return pay_date, data

def main():
    if len(sys.argv) < 2:
        print("Usage: python paystub2csv.py [old_paystub.pdf] <new_paystub.pdf>")
        sys.exit(1)
        
    if len(sys.argv) == 2:
        old_pdf = None
        new_pdf = sys.argv[1]
    else:
        old_pdf = sys.argv[1]
        new_pdf = sys.argv[2]
    
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
        
        # Display the line item name using the newest paystub's formatting
        def get_name(k):
            if k in new_data[category]: return new_data[category][k]['name']
            return old_data[category][k]['name']
            
        for key in sorted(all_keys, key=lambda k: get_name(k).lower()):
            display_name = get_name(key)
            new_ytd = new_data[category].get(key, {}).get('ytd', 0.0)
            old_ytd = old_data[category].get(key, {}).get('ytd', 0.0)
            
            delta = new_ytd if is_january else new_ytd - old_ytd
            
            # Skip rows with no monthly activity
            if abs(delta) < 0.01:
                continue
                
            # Flip signs for debits
            if category in ['Deductions', 'Taxes']:
                delta = -delta
                
            writer.writerow([new_date, f"{category}: {display_name}", f"{delta:.2f}"])

if __name__ == '__main__':
    main()
