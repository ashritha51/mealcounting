from flask import Flask, redirect, url_for,render_template,request,session,flash, send_file, jsonify
from flask_pymongo import PyMongo
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
from barcode.writer import ImageWriter
import os
from flask_cors import CORS
from barcode import generate
from flask_mail import Mail, Message
import requests
from collections import OrderedDict

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['MONGO_URI']="mongodb://localhost:27017/meal"
mongo=PyMongo(app)
CORS(app)
FAST2SMS_API_KEY = "mOKg56nPX0S81bUhxjE7DsJMGzZC4FolRY9yfuLdtHqBV3cNkwQ5WjX3vYhF0alUJ8CwGNBe7dmqgc29"

MORNING_START = 7
MORNING_END = 9
EVENING_START = 14  # 3 PM
EVENING_END = 23  # 5 PM
BARCODE_FOLDER = "static/barcodes/"
if not os.path.exists(BARCODE_FOLDER):
    os.makedirs(BARCODE_FOLDER)

students_collection = mongo.db.students  
meals_collection = mongo.db.meals        
counts_collection = mongo.db.meal_counts
mess_collection = mongo.db.mess_staff
menu_collection=mongo.db.menu


def reset_meal_data():
    print("🔄 Resetting meal data...")
    meals_collection.delete_many({})
    counts_collection.update_one({}, {"$set": {"veg": 0, "nonveg": 0}}, upsert=True)
    print("✅ Meal data reset successfully!")
    
    
# def send_bulk_sms():
#     students = students_collection.find({}, {"phone_number": 1})  # Get student phone numbers
#     phone_numbers = [str(student["phone_number"]) for student in students if "phone_number" in student]
    
#     if not phone_numbers:
#         print("No phone numbers found!")
#         return

#     message = "⚠️ Reminder: Meal selection time is about to end in 30 minutes. Hurry up!"
    
#     url = "https://www.fast2sms.com/dev/bulkV2"
#     headers = {
#         "authorization": FAST2SMS_API_KEY,
#         "Content-Type": "application/json"
#     }
#     payload = {
#         "route": "q",
#         "message": message,
#         "language": "english",
#         "flash": 0,
#         "numbers": ",".join(phone_numbers)
#     }

#     response = requests.post(url, json=payload, headers=headers)
#     print("📩 SMS Response:", response.json())



scheduler = BackgroundScheduler()
scheduler.add_job(reset_meal_data, 'cron', hour=7, minute=0)  # Reset at 7 AM
scheduler.add_job(reset_meal_data, 'cron', hour=16, minute=47)  # Reset at 3 PM
# scheduler.add_job(send_bulk_sms, "cron", hour=8, minute=30)  # 8:30 AM reminder
# scheduler.add_job(send_bulk_sms, "cron", hour=16, minute=5)
scheduler.start()


def is_meal_selection_allowed():
    """Check if current time is within allowed meal selection hours."""
    now = datetime.now()
    current_hour = now.hour
    return (MORNING_START <= current_hour < MORNING_END) or (EVENING_START <= current_hour < EVENING_END)


@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        student = students_collection.find_one({"username": username})

        if student and check_password_hash(student["password"], password):
            print(".....")
            session['student'] = username
            session['student_id'] = student.get("student_id")
            
            if student.get("is_first_login", False):
                #session['student'] = username
                return redirect(url_for('change_password'))

            # session['student'] = username
            return redirect(url_for('student_dashboard'))
        
        print("out")
        flash("Invalid credentials. Try again.", "danger")

    return render_template('studentlogin.html')


@app.route('/edit_profile')
def edit_profile():
    if 'student' not in session:
        return redirect(url_for('login'))
    
    student = students_collection.find_one({"username": session['student']}, {"_id": 0})
    
    return render_template('edit_profile.html', student=student)


@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'student' not in session:
        return redirect(url_for('login'))

    password = request.form.get('password')

    if password:
        hashed_password = generate_password_hash(password)
        students_collection.update_one({"username": session['student']}, {"$set": {"password": hashed_password}})
        flash("Password updated successfully!", "success")

    return redirect(url_for('student_dashboard'))


@app.route('/change_password', methods=['POST','GET'])
def change_password():
    if 'student' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        new_pass = request.form['new_password']

        students_collection.update_one(
            {"username":session['student']},
            {"$set": {"password": generate_password_hash(new_pass), "is_first_login":False}}
        )

        flash("Password changed successfully!", "success")
        
        return redirect(url_for('student_dashboard'))
    
    return render_template('changepassword.html')


@app.route("/student_dashboard")
def student_dashboard():
    if "student" in session:
        student_id = session.get("student_id")
        return render_template("studentdashboard.html", student=session["student"], student_id=student_id)
    return redirect(url_for("login"))


@app.route('/meal_selection',methods=['GET'])
def meal_selection():
    if 'student' not in session:
        return redirect(url_for('login'))

    return render_template('mealselection.html')


@app.route('/select_meal',methods=['POST'])
def select_meal():
    if 'student' not in session:
        return redirect(url_for('login'))
    
    if not is_meal_selection_allowed():
        return "Meal selection is only allowed from 7 AM - 9 AM and 3 PM - 5 PM."

    student = session['student']
    student_id = session.get("student_id")
    meal_type = request.form.get('meal_type')
    
    if meal_type not in ["veg", "nonveg"]:
        return "Invalid meal selection!"  
    
    existing_meal = meals_collection.find_one({"username": student})
    
    if existing_meal:
        previous_meal = existing_meal['meal_type']
        # meals_collection.update_one({"username": student}, {"$set": {"meal_type": meal_type, "student_id": student_id}})
        meals_collection.update_one(
            {"student_id": student_id},
            {"$set": {"meal_type": meal_type}}
        )
        counts_collection.update_one({}, {"$inc": {previous_meal: -1, meal_type: 1}})
    else:
        # meals_collection.insert_one({"username": student, "student_id": student_id, "meal_type": meal_type})
        meals_collection.insert_one({
            "username": student,
            "student_id": student_id,
            "meal_type": meal_type,
            "status": "pending",
        })
        counts_collection.update_one({}, {"$inc": {meal_type: 1}}, upsert=True)

    
    return redirect(url_for('meal_card'))

@app.route("/meal_card")
def meal_card():
    if "student" not in session:
        return redirect(url_for("login"))

    student = session["student"]

    # Retrieve student details
    student_data = students_collection.find_one({"username": student}, {"_id": 0, "student_id": 1})

    if not student_data:
        return "Student not found in the database!"

    student_id = student_data.get("student_id")

    # Retrieve meal type
    meal_data = meals_collection.find_one({"username": student}, {"_id": 0, "meal_type": 1})

    if not meal_data:
        return "Meal Type Not Selected!"

    meal_type = meal_data.get("meal_type")

    # Redirect to the new meal card route
    return redirect(url_for("mealcard", student_id=student_id, meal_type=meal_type))




if not os.path.exists("static"):
    os.makedirs("static")


@app.route('/generate_barcode', methods=['POST'])
def generate_barcode():
    data = request.form.get('data')
    
    if not data:
        return "Missing barcode data", 400

    buffer = BytesIO()
    generate('code128', data, writer=ImageWriter(), output=buffer)
    buffer.seek(0)

    return send_file(buffer, mimetype='image/png')



@app.route('/mealcard/<student_id>/<meal_type>')
def mealcard(student_id, meal_type):
    barcode_data = f"{student_id}{meal_type}"  # Unique barcode data
    
    return render_template("mealcard.html", student_id=student_id, meal_type=meal_type, barcode_data=barcode_data)



@app.route("/scan_meal", methods=["GET", "POST"])
def scan_meal():
    """Mess staff can scan student meal barcodes."""
    if "user_type" not in session or session["user_type"] != "mess":
        flash("Access denied!", "danger")
        return redirect(url_for("mess_login"))

    if request.method == "POST":
        barcode_data = request.form.get("barcode", "").strip()  # Trim spaces and new lines

        if not barcode_data:
            flash("Invalid scan!", "danger")
            return redirect(url_for("scan_meal"))

        print("🔍 Scanned Barcode Data:", barcode_data)  # Debugging

        # Correct student ID and meal type extraction
        if barcode_data.endswith("nonveg"):
            student_id = barcode_data[:-6]  # Remove "nonveg"
            meal_type = "nonveg"
        elif barcode_data.endswith("veg"):
            student_id = barcode_data[:-3]  # Remove "veg"
            meal_type = "veg"
        else:
            flash("Invalid barcode format!", "danger")
            print("❌ Incorrect Barcode Format:", barcode_data)  # Debugging
            return redirect(url_for("scan_meal"))

        print("✅ Extracted Student ID:", student_id)
        print("✅ Extracted Meal Type:", meal_type)

        # Find the meal record in the database
        meal_record = meals_collection.find_one(
            {"student_id": student_id, "meal_type": meal_type}
        )

        if not meal_record:
            flash("Meal not found!", "danger")
            print("❌ No meal record found for:", student_id, meal_type)  # Debugging
            return redirect(url_for("scan_meal"))

        # Check if the meal has already been used
        if meal_record.get("status", "").lower() == "used":
            flash(f"Meal for {student_id} ({meal_type}) already marked as eaten!", "warning")
            print("⚠️ Meal already used:", student_id, meal_type)  # Debugging
            return redirect(url_for("scan_meal"))


        # Mark the meal as used
        meals_collection.update_one(
            {"student_id": student_id, "meal_type": meal_type},
            {"$set": {"status": "used"}}
        )

        flash(f"✅ Meal for {student_id} ({meal_type}) marked as eaten.", "success")
        print("✔️ Meal status updated for:", student_id, meal_type)  # Debugging

        return redirect(url_for("scan_meal"))

    # Retrieve all eaten meals
    eaten_meals = list(meals_collection.find({"status": "used"}, {"_id": 0}))

    return render_template("scanmeal.html", eaten_meals=eaten_meals)


@app.route('/get_menu',methods=['GET'])
# def get_menu():
#     menu = menu_collection.find_one({}, {"_id": 0})
#     return render_template("menu.html", menu=menu)
def get_menu():
    menu = menu_collection.find_one({}, {"_id": 0})  # Fetch menu from MongoDB

    # Define the correct order of days
    correct_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    # Reorder menu dictionary
    ordered_menu = OrderedDict()
    for day in correct_order:
        if day in menu:
            ordered_menu[day] = menu[day]

    return render_template("menu.html", menu=ordered_menu)



@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully!", "info")
    return redirect(url_for("login"))



@app.route('/mess_login', methods=['GET', 'POST'])
def mess_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        mess_staff = mongo.db.mess_staff.find_one({"username": username})

        if mess_staff and check_password_hash(mess_staff["password"], password):
            session['user_type'] = "mess"
            session['username'] = username
            return redirect(url_for('mess_dashboard'))

        flash("Invalid credentials. Try again.", "danger")

    return render_template('messlogin.html')  # Create this HTML file



@app.route("/mess_dashboard")
def mess_dashboard():
    """Mess staff dashboard with options: Scan Meal and View Selections"""
    if "user_type" not in session or session["user_type"] != "mess":
        flash("Access denied!", "danger")
        return redirect(url_for("mess_login"))

    return render_template("messdashboard.html")  # New HTML page for mess staff



@app.route('/mess_staff')
def mess_staff():   
    meal_counts = counts_collection.find_one({}, {"_id": 0})
    
    if not meal_counts:
        meal_counts = {"veg": 0, "nonveg": 0}
    
    student_meal_list = list(meals_collection.find({}, {"_id": 0, "username": 1, "meal_type": 1}))
    
    return render_template('messstaff.html', meal_counts=meal_counts,student_meal_list=student_meal_list)


if __name__ == "__main__":
    if counts_collection.count_documents({}) == 0:
        counts_collection.insert_one({"veg": 0, "nonveg": 0})
    app.run(debug=True)