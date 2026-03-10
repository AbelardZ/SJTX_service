# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify
from datetime import datetime
from divination import perform_divination, create_wapp
import webbrowser
from threading import Timer
import mysql.connector
from config import DB_CONFIG
import re

app = Flask(__name__)

def get_available_years():
    """Get list of available year tables from database"""
    years = []
    try:
        cnx = mysql.connector.connect(**DB_CONFIG)
        cursor = cnx.cursor()
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        
        for (table_name,) in tables:
            # Match tables like "2025年"
            match = re.match(r'^(\d{4})年$', table_name)
            if match:
                years.append(match.group(1))
        
        cursor.close()
        cnx.close()
    except Exception as e:
        print(f"Error fetching tables: {e}")
    
    # Sort years descending
    years.sort(reverse=True)
    return years

@app.route('/history')
def history():
    available_years = get_available_years()
    current_year = datetime.now().strftime('%Y')
    
    # Get query params
    year_table = request.args.get('year_table', current_year)
    search_date = request.args.get('search_date', '')
    search_subject = request.args.get('search_subject', '')
    search_user = request.args.get('search_user', '')
    
    results = []
    
    # Only query if we have a valid year table
    if year_table in available_years:
        table_name = f"{year_table}年"
        try:
            cnx = mysql.connector.connect(**DB_CONFIG)
            cursor = cnx.cursor(dictionary=True)
            
            query = f"SELECT * FROM `{table_name}` WHERE 1=1"
            params = []
            
            if search_date:
                # Database stores time as 'YYYY-MM-DD HH:MM' string
                query += " AND 时间 LIKE %s"
                params.append(f"{search_date}%")
            
            if search_subject:
                query += " AND 标的 LIKE %s"
                params.append(f"%{search_subject}%")
                
            if search_user:
                query += " AND 用户 LIKE %s"
                params.append(f"%{search_user}%")
            
            query += " ORDER BY id DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Format for template
            for row in rows:
                # Reconstruct yaos string for display
                yaos_str = f"{row['初爻']}{row['二爻']}{row['三爻']}{row['四爻']}{row['五爻']}{row['上爻']}"
                results.append({
                    'id': row['id'],
                    'time': row['时间'],
                    'user': row['用户'],
                    'subject': row['标的'],
                    'mode': row['起卦方式'],
                    'month_gz': f"{row['月干']}{row['月支']}",
                    'day_gz': f"{row['日干']}{row['日支']}",
                    'yaos': yaos_str
                })
                
            cursor.close()
            cnx.close()
        except Exception as e:
            print(f"Error querying history: {e}")

    return render_template('history.html', 
                         results=results,
                         available_years=available_years,
                         current_year=year_table,
                         search_date=search_date,
                         search_subject=search_subject,
                         search_user=search_user)

@app.route('/history/view/<year_table>/<int:record_id>')
def view_history(year_table, record_id):
    # Validate year_table format to prevent SQL injection
    if not re.match(r'^\d{4}$', year_table):
        return "Invalid year", 400
        
    table_name = f"{year_table}年"
    
    try:
        cnx = mysql.connector.connect(**DB_CONFIG)
        cursor = cnx.cursor(dictionary=True)
        
        query = f"SELECT * FROM `{table_name}` WHERE id = %s"
        cursor.execute(query, (record_id,))
        row = cursor.fetchone()
        
        cursor.close()
        cnx.close()
        
        if not row:
            return "Record not found", 404
            
        # Parse time
        # Time format in DB: 'YYYY-MM-DD HH:MM'
        # Handle potential format variations (e.g. '12-04-22-37')
        time_str = row['时间']
        try:
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
        except ValueError:
            try:
                # Try to extract numbers using regex
                nums = re.findall(r'\d+', time_str)
                if len(nums) == 5: # YYYY MM DD HH MM
                    dt = datetime(int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3]), int(nums[4]))
                elif len(nums) == 4: # MM DD HH MM (use year from table)
                    dt = datetime(int(year_table), int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3]))
                else:
                    # Fallback to current time if parsing fails completely, to allow viewing
                    print(f"Warning: Could not parse date '{time_str}', using current time.")
                    dt = datetime.now()
            except Exception as e:
                print(f"Error parsing date '{time_str}': {e}")
                dt = datetime.now()
        
        # Parse Yaos
        # DB columns: 初爻, 二爻, ... 上爻
        # wapp expects list of strings ['1', '2', '3', '4'] (bottom to top)
        ygua = [
            str(row['初爻']),
            str(row['二爻']),
            str(row['三爻']),
            str(row['四爻']),
            str(row['五爻']),
            str(row['上爻'])
        ]
        
        # Ganzhi
        gz_month = f"{row['月干']}{row['月支']}"
        gz_day = f"{row['日干']}{row['日支']}"
        
        # Create wapp object
        wapp = create_wapp(
            subject=row['标的'],
            ygua=ygua,
            year=dt.year,
            month=dt.month,
            day=dt.day,
            hour=dt.hour,
            minute=dt.minute,
            gz_month=gz_month,
            gz_day=gz_day
        )
        
        result_data = wapp.get_paipan_data()
        
        # Construct ganzhi_info and ygua_codes for template compatibility
        ganzhi_info = {
            'month_gan': row['月干'],
            'month_zhi': row['月支'],
            'day_gan': row['日干'],
            'day_zhi': row['日支']
        }
        
        # Prepare yao_list for manual input display (Top to Bottom)
        # ygua is Bottom to Top ['1', '2', '3', '4', ...]
        mapping_rev = {'1': '少阳', '2': '少阴', '3': '老阳', '4': '老阴'}
        yao_list_bottom_to_top = [mapping_rev.get(code, '少阳') for code in ygua]
        yao_list = list(reversed(yao_list_bottom_to_top))
        
        # Render index.html with the data
        return render_template('index.html',
            result_data=result_data,
            subject=row['标的'],
            user=row['用户'],
            remarks=row.get('备注', ''),
            year_table=year_table,
            record_id=record_id,
            date_str=dt.strftime('%Y-%m-%d'),
            hour=dt.hour,
            minute=dt.minute,
            ganzhi_info=ganzhi_info,
            ygua_codes=ygua,
            yao_list=yao_list,
            month_gan=row['月干'],
            month_zhi=row['月支'],
            day_gan=row['日干'],
            day_zhi=row['日支'],
            input_mode='manual',
            is_history=True 
        )

    except Exception as e:
        print(f"Error viewing history: {e}")
        return f"Error: {e}", 500

@app.route('/update_remarks', methods=['POST'])
def update_remarks():
    try:
        data = request.json
        year_table = data.get('year_table')
        record_id = data.get('record_id')
        remarks = data.get('remarks')
        
        if not year_table or not record_id:
             return jsonify({"status": "error", "message": "Missing parameters"}), 400

        table_name = f"{year_table}年"
        
        cnx = mysql.connector.connect(**DB_CONFIG)
        cursor = cnx.cursor()
        
        update_sql = f"UPDATE `{table_name}` SET 备注 = %s WHERE id = %s"
        cursor.execute(update_sql, (remarks, record_id))
        cnx.commit()
        
        cursor.close()
        cnx.close()
        
        return jsonify({"status": "success", "message": "备注更新成功"})
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/save', methods=['POST'])
def save_result():
    try:
        data = request.json
        # Extract data
        input_mode = data.get('input_mode')
        # date_str format from frontend: YYYY-MM-DD HH:MM
        date_str_full = data.get('date_str') 
        dt = datetime.strptime(date_str_full, '%Y-%m-%d %H:%M')
        year = dt.year
        table_name = f"{year}年"
        
        month_gan = data.get('month_gan')
        month_zhi = data.get('month_zhi')
        day_gan = data.get('day_gan')
        day_zhi = data.get('day_zhi')
        
        # Yaos: List of codes '1','2','3','4' (Bottom to Top)
        yaos = data.get('yaos') 
        
        subject = data.get('subject')
        user = data.get('user')
        remarks = data.get('remarks', '')
        
        # Connect to DB
        cnx = mysql.connector.connect(**DB_CONFIG)
        cursor = cnx.cursor()
        
        # Create Table if not exists
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
            id INT AUTO_INCREMENT PRIMARY KEY,
            起卦方式 VARCHAR(20),
            时间 VARCHAR(20),
            月干 VARCHAR(10),
            月支 VARCHAR(10),
            日干 VARCHAR(10),
            日支 VARCHAR(10),
            初爻 CHAR(1),
            二爻 CHAR(1),
            三爻 CHAR(1),
            四爻 CHAR(1),
            五爻 CHAR(1),
            上爻 CHAR(1),
            标的 VARCHAR(255),
            用户 VARCHAR(255),
            备注 TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        cursor.execute(create_table_sql)
        
        # Check if '备注' column exists (for existing tables)
        cursor.execute(f"SHOW COLUMNS FROM `{table_name}` LIKE '备注'")
        if not cursor.fetchone():
            try:
                cursor.execute(f"ALTER TABLE `{table_name}` ADD COLUMN 备注 TEXT")
            except Exception as e:
                print(f"Error adding column: {e}")

        # Insert
        insert_sql = f"""
        INSERT INTO `{table_name}` 
        (起卦方式, 时间, 月干, 月支, 日干, 日支, 初爻, 二爻, 三爻, 四爻, 五爻, 上爻, 标的, 用户, 备注)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        # Format time as YYYY-MM-DD HH:MM for consistency with new parsing logic
        # Or keep old format if preferred, but let's stick to what we parse:
        # The parsing logic handles 'YYYY-MM-DD HH:MM' or 'MM-DD-HH-MM' or 'YYYY MM DD HH MM'
        # Let's save as standard 'YYYY-MM-DD HH:MM' to avoid future issues
        time_formatted = dt.strftime('%Y-%m-%d %H:%M')
        
        # Map input mode to Chinese if needed, or keep as is (manual/random/single)
        mode_map = {'manual': '指定', 'random': '多随机', 'single': '单随机'}
        mode_cn = mode_map.get(input_mode, input_mode)

        values = (
            mode_cn, time_formatted, 
            month_gan, month_zhi, day_gan, day_zhi,
            yaos[0], yaos[1], yaos[2], yaos[3], yaos[4], yaos[5],
            subject, user, remarks
        )
        
        cursor.execute(insert_sql, values)
        cnx.commit()
        cursor.close()
        cnx.close()
        
        return jsonify({"status": "success", "message": "保存成功"})
        
    except Exception as e:
        print(e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/', methods=['GET', 'POST'])
def index():
    result = ""
    result_data = None
    subject = ""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    hour = now.hour
    minute = now.minute
    yao_list = ['少阳'] * 6  # Default values
    input_mode = 'manual'
    ygua_codes = [] # Store codes for DB (Bottom to Top)
    ganzhi_info = {} # Store GanZhi for DB

    if request.method == 'POST':
        try:
            subject = request.form.get('subject', '')
            date_str = request.form.get('date')
            hour = int(request.form.get('hour'))
            minute = int(request.form.get('minute'))
            input_mode = request.form.get('input_mode', 'manual')
            
            # Parse date
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            year, month, day = dt.year, dt.month, dt.day

            ygua_codes = []
            
            if input_mode == 'manual':
                # Get Yao (Top to Bottom from form, index 0 is Top)
                input_yaos = []
                for i in range(6):
                    val = request.form.get(f'yao_{i}')
                    input_yaos.append(val)
                
                yao_list = input_yaos  # Keep for re-rendering form
                
                # Convert to internal format (1,2,3,4)
                mapping = {'少阳': '1', '少阴': '2', '老阳': '3', '老阴': '4'}
                ygua_codes = [mapping[y] for y in input_yaos]
                
                # The logic expects Bottom to Top, but UI is Top to Bottom
                ygua_codes = list(reversed(ygua_codes))

            elif input_mode == 'random':
                # Random inputs (Top to Bottom)
                # Remainder map: 0->4(老阴), 1->1(少阳), 2->2(少阴), 3->3(老阳)
                remainder_map = {0: '4', 1: '1', 2: '2', 3: '3'}
                codes_top_to_bottom = []
                
                for i in range(6):
                    val_str = request.form.get(f'random_val_{i}', '')
                    try:
                        val = int(val_str)
                        if val <= 10:
                            raise ValueError(f"第{6-i}爻的随机数必须大于10")
                        code = remainder_map[val % 4]
                        codes_top_to_bottom.append(code)
                    except ValueError as ve:
                        raise ValueError(f"随机数输入错误: {str(ve)}")
                
                ygua_codes = list(reversed(codes_top_to_bottom))

            elif input_mode == 'single':
                # Single random number (6 digits)
                val_str = request.form.get('single_random_val', '').strip()
                if not val_str.isdigit() or len(val_str) != 6:
                    raise ValueError("单随机模式需要输入6位数字")
                
                digits = [int(d) for d in val_str]
                if any(d < 1 or d > 8 for d in digits):
                    raise ValueError("单随机模式每位数字必须在1-8之间")
                
                # Original logic: digits_bottom_to_top = list(reversed(digits))
                # Input "123456" -> digits=[1,2,3,4,5,6] -> reversed=[6,5,4,3,2,1]
                # 6 is Bottom, 1 is Top.
                digits_bottom_to_top = list(reversed(digits))
                
                remainder_map = {0: '4', 1: '1', 2: '2', 3: '3'}
                ygua_codes = []
                for d in digits_bottom_to_top:
                    ygua_codes.append(remainder_map[d % 4])

            # Gan-Zhi Inputs
            gz_year = request.form.get('gz_year', '')
            gz_month = request.form.get('gz_month', '')
            gz_day = request.form.get('gz_day', '')
            gz_hour = request.form.get('gz_hour', '')
            
            # If parts are provided separately (e.g. month_gan, month_zhi), combine them
            # But for simplicity, let's assume the form sends combined strings or we combine them here.
            # Let's use separate fields for flexibility in UI
            
            def combine_gz(gan, zhi):
                if gan and zhi: return gan + zhi
                return None

            gz_year_val = combine_gz(request.form.get('year_gan'), request.form.get('year_zhi'))
            gz_month_val = combine_gz(request.form.get('month_gan'), request.form.get('month_zhi'))
            gz_day_val = combine_gz(request.form.get('day_gan'), request.form.get('day_zhi'))
            gz_hour_val = combine_gz(request.form.get('hour_gan'), request.form.get('hour_zhi'))

            wapp, output = perform_divination(subject, ygua_codes, year, month, day, hour, minute,
                                              gz_year=gz_year_val, gz_month=gz_month_val, 
                                              gz_day=gz_day_val, gz_hour=gz_hour_val)
            result = output
            result_data = wapp.get_paipan_data()
            
            # Extract GanZhi for DB
            # wapp.wanzu = [year_gz, month_gz, day_gz, hour_gz]
            if hasattr(wapp, 'wanzu'):
                mgz = wapp.wanzu[1]
                dgz = wapp.wanzu[2]
                ganzhi_info = {
                    'month_gan': mgz[0],
                    'month_zhi': mgz[1],
                    'day_gan': dgz[0],
                    'day_zhi': dgz[1]
                }
            
        except Exception as e:
            result = f"发生错误: {str(e)}"

    return render_template('index.html', 
                           result=result, 
                           result_data=result_data,
                           subject=subject, 
                           date_str=date_str, 
                           hour=hour, 
                           minute=minute,
                           yao_list=yao_list,
                           input_mode=input_mode,
                           ygua_codes=ygua_codes,
                           ganzhi_info=ganzhi_info,
                           # Pass back Gan-Zhi selections
                           year_gan=request.form.get('year_gan', ''),
                           year_zhi=request.form.get('year_zhi', ''),
                           month_gan=request.form.get('month_gan', ''),
                           month_zhi=request.form.get('month_zhi', ''),
                           day_gan=request.form.get('day_gan', ''),
                           day_zhi=request.form.get('day_zhi', ''),
                           hour_gan=request.form.get('hour_gan', ''),
                           hour_zhi=request.form.get('hour_zhi', ''))

def run_web():
    print("启动 Web 服务...")
    print("请在浏览器访问 http://127.0.0.1:5000")
    # Open browser automatically
    Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(debug=False, port=5000)

if __name__ == '__main__':
    run_web()
