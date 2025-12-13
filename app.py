from flask import Flask, render_template, request, jsonify, send_file
import json
import os
from datetime import datetime, timedelta
import calendar
from io import BytesIO

app = Flask(__name__)

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Load configuration
def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

config = load_config()
TIMETABLE = config['timetable']
PERIODS = config['periods']

def load_data():
    """Load attendance data from JSON file"""
    try:
        with open('data/attendance.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_data(data):
    """Save attendance data to JSON file"""
    with open('data/attendance.json', 'w') as f:
        json.dump(data, f, indent=2)

def get_month_dates(year, month):
    """Get all dates for a month"""
    num_days = calendar.monthrange(year, month)[1]
    return [datetime(year, month, day) for day in range(1, num_days + 1)]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/calendar/<int:year>/<int:month>')
def get_calendar(year, month):
    """Get calendar data for specific month"""
    dates = get_month_dates(year, month)
    calendar_data = []
    
    for date in dates:
        day_name = date.strftime('%A')
        date_str = date.strftime('%Y-%m-%d')
        
        if day_name == 'Sunday':
            calendar_data.append({
                'date': date_str,
                'day': day_name,
                'type': 'sunday'
            })
        elif day_name == 'Wednesday':
            calendar_data.append({
                'date': date_str,
                'day': day_name,
                'type': 'off'
            })
        else:
            day_schedule = TIMETABLE.get(day_name, {})
            periods_data = []
            
            for period, subject_data in day_schedule.items():
                # subject_data is a list [subject, faculty] in JSON
                periods_data.append({
                    'period': period,
                    'subject': subject_data[0],
                    'faculty': subject_data[1],
                    'time': PERIODS.get(period, '')
                })
            
            calendar_data.append({
                'date': date_str,
                'day': day_name,
                'type': 'class',
                'periods': periods_data
            })
    
    return jsonify(calendar_data)

@app.route('/api/attendance/<int:year>/<int:month>')
def get_attendance(year, month):
    """Get attendance data for specific month"""
    data = load_data()
    month_key = f"{year}-{month:02d}"
    return jsonify(data.get(month_key, {}))

@app.route('/api/attendance/<int:year>/<int:month>', methods=['POST'])
def update_attendance(year, month):
    """Update attendance data"""
    new_data = request.json
    month_key = f"{year}-{month:02d}"
    
    data = load_data()
    data[month_key] = new_data
    save_data(data)
    
    return jsonify({'status': 'success'})

@app.route('/api/holiday/<int:year>/<int:month>/<date>', methods=['POST'])
def mark_holiday(year, month, date):
    """Mark a date as holiday"""
    month_key = f"{year}-{month:02d}"
    
    data = load_data()
    if month_key not in data:
        data[month_key] = {}
    
    # Mark all periods for this date as holiday
    data[month_key][date] = {'HOLIDAY': True}
    save_data(data)
    
    return jsonify({'status': 'success'})

@app.route('/api/holiday/<int:year>/<int:month>/<date>', methods=['DELETE'])
def unmark_holiday(year, month, date):
    """Unmark a date as holiday"""
    month_key = f"{year}-{month:02d}"
    
    data = load_data()
    if month_key in data and date in data[month_key]:
        if 'HOLIDAY' in data[month_key][date]:
            del data[month_key][date]['HOLIDAY']
            # If no other data, remove the date entry
            if not data[month_key][date]:
                del data[month_key][date]
        save_data(data)
    
    return jsonify({'status': 'success'})

@app.route('/api/summary/<int:year>/<int:month>')
def get_summary(year, month):
    """Get attendance summary"""
    data = load_data()
    month_key = f"{year}-{month:02d}"
    
    if month_key not in data:
        return jsonify({})
    
    # Calculate statistics
    subject_stats = {'OVERALL': {'total': 0, 'present': 0}}
    
    # Initialize subjects from configuration
    for day_schedule in TIMETABLE.values():
        for subject_info in day_schedule.values():
            # config puts [subject, faculty]
            if isinstance(subject_info, list) and len(subject_info) > 0:
                subject = subject_info[0]
                if subject and subject not in ['LUNCH', 'OFF', '-']:
                    if subject not in subject_stats:
                        subject_stats[subject] = {'total': 0, 'present': 0}
    
    for date_str, day_data in data[month_key].items():
        # Skip holiday days
        if 'HOLIDAY' in day_data and day_data['HOLIDAY']:
            continue
            
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        day_name = date_obj.strftime('%A')
        
        if day_name in ['Sunday', 'Wednesday']:
            continue
            
        day_schedule = TIMETABLE[day_name]
        
        for period, attendance in day_data.items():
            if period == 'HOLIDAY':
                continue
                
            subject_data = day_schedule.get(period)
            if subject_data:
                subject = subject_data[0]
                if subject in subject_stats:
                    subject_stats[subject]['total'] += 1
                    subject_stats['OVERALL']['total'] += 1
                    
                    if attendance == 'P':
                        subject_stats[subject]['present'] += 1
                        subject_stats['OVERALL']['present'] += 1
    
    # Calculate percentages
    summary = {}
    for subject, stats in subject_stats.items():
        if stats['total'] > 0:
            percentage = (stats['present'] / stats['total']) * 100
        else:
            percentage = 0
            
        summary[subject] = {
            'total': stats['total'],
            'present': stats['present'],
            'absent': stats['total'] - stats['present'],
            'percentage': round(percentage, 1)
        }
    
    return jsonify(summary)

@app.route('/api/export/csv/<int:year>/<int:month>')
def export_csv(year, month):
    """Export attendance as CSV"""
    data = load_data()
    month_key = f"{year}-{month:02d}"
    
    if month_key not in data:
        return jsonify({'error': 'No data'}), 404
    
    # Create CSV content
    csv_lines = ['Date,Day,Period,Subject,Faculty,Attendance,Status']
    
    for date_str, day_data in data[month_key].items():
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        day_name = date_obj.strftime('%A')
        
        if 'HOLIDAY' in day_data and day_data['HOLIDAY']:
            csv_lines.append(f'{date_str},{day_name},All,---,---,---,HOLIDAY')
            continue
            
        if day_name in ['Sunday', 'Wednesday']:
            continue
            
        day_schedule = TIMETABLE[day_name]
        
        for period, attendance in day_data.items():
            if period == 'HOLIDAY':
                continue
                
            subject_data = day_schedule.get(period)
            if subject_data:
                subject, faculty = subject_data[0], subject_data[1]
                csv_lines.append(f'{date_str},{day_name},{period},{subject},{faculty},{attendance},Regular')
    
    csv_content = '\n'.join(csv_lines)
    
    # Return as file
    output = BytesIO()
    output.write(csv_content.encode('utf-8'))
    output.seek(0)
    
    filename = f"attendance_{year}_{month:02d}.csv"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='text/csv')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)