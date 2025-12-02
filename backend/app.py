from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity,
    set_access_cookies, unset_jwt_cookies
)
import joblib
import numpy as np
import os
from datetime import timedelta, datetime
from remedies_data import remedies_data
from dotenv import load_dotenv
from skin_model_loader import SkinDiseaseModel
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super-secret-key-change-this-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///users.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-this-in-production')
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['JWT_COOKIE_CSRF_PROTECT'] = os.environ.get('FLASK_ENV') == 'production'
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
app.config['JWT_COOKIE_SAMESITE'] = 'None' if os.environ.get('FLASK_ENV') == 'production' else 'Lax'

# Extensions
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# CORS Configuration
# In production, FRONTEND_URL should be set to the deployed frontend URL (e.g., https://healix.vercel.app)
frontend_url = os.environ.get('FRONTEND_URL', "http://localhost:5173")
CORS(app, supports_credentials=True, origins=[frontend_url, "https://healixv2.vercel.app", "http://localhost:5173", "http://127.0.0.1:5173"])

# Database Model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    predictions = db.relationship('Prediction', backref='user', lazy=True)

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    disease = db.Column(db.String(100), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    symptoms = db.Column(db.Text, nullable=False) # Storing as comma-separated string

class DietPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    plan_data = db.Column(db.Text, nullable=False) # JSON string of the plan
    goal = db.Column(db.String(50), nullable=False)

class ExerciseLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    exercise_type = db.Column(db.String(100), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    calories_burnt = db.Column(db.Integer, nullable=False)

class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(20))
    height = db.Column(db.Float) # cm
    weight = db.Column(db.Float) # kg
    blood_type = db.Column(db.String(5))
    allergies = db.Column(db.String(200))

class SkinAnalysisLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    condition_name = db.Column(db.String(100), nullable=False)
    probability = db.Column(db.Float, nullable=False)
    image_path = db.Column(db.String(200)) # Optional: store path if we were saving images

class EmergencyContact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120))

# ... (Load models section)

# ... (Auth routes)

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'message': 'Healix Backend is running!'})

@app.route('/generate-diet', methods=['POST'])
@jwt_required()
def generate_diet():
    data = request.json
    
    # Extract parameters
    age = int(data.get('age'))
    gender = data.get('gender')
    weight = float(data.get('weight')) # kg
    height = float(data.get('height')) # cm
    activity = data.get('activity') # sedentary, light, moderate, active, very_active
    goal = data.get('goal') # lose, maintain, gain
    preference = data.get('preference') # veg, non-veg, vegan
    
    # 1. Calculate BMR (Mifflin-St Jeor Equation)
    if gender.lower() == 'male':
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
        
    # 2. Calculate TDEE
    activity_multipliers = {
        'sedentary': 1.2,
        'light': 1.375,
        'moderate': 1.55,
        'active': 1.725,
        'very_active': 1.9
    }
    tdee = bmr * activity_multipliers.get(activity, 1.2)
    
    # 3. Adjust for Goal
    if goal == 'lose':
        target_calories = tdee - 500
    elif goal == 'gain':
        target_calories = tdee + 500
    else:
        target_calories = tdee
        
    # 4. Generate Meal Plan (Rule-Based Expert System)
    # Simplified database of meals
    meals_db = {
        'breakfast': {
            'veg': ['Oatmeal with fruits and nuts', 'Vegetable Poha', 'Paneer Sandwich'],
            'non-veg': ['Scrambled Eggs with Toast', 'Chicken Sausage Omelette', 'Egg Bhurji'],
            'vegan': ['Oatmeal with almond milk', 'Tofu Scramble', 'Fruit Smoothie Bowl']
        },
        'lunch': {
            'veg': ['Dal, Rice, and Mixed Veg Curry', 'Roti, Paneer Butter Masala, Salad', 'Rajma Chawal'],
            'non-veg': ['Chicken Curry, Rice, Salad', 'Grilled Fish with Quinoa', 'Egg Curry with Roti'],
            'vegan': ['Chickpea Curry with Rice', 'Lentil Soup with Quinoa', 'Stir-fried Tofu with Veggies']
        },
        'dinner': {
            'veg': ['Vegetable Soup and Salad', 'Roti with Dal', 'Khichdi'],
            'non-veg': ['Grilled Chicken Salad', 'Fish Tacos', 'Chicken Stir-fry'],
            'vegan': ['Lentil Soup', 'Quinoa Salad with Roasted Veggies', 'Tofu Stir-fry']
        },
        'snack': {
            'veg': ['Greek Yogurt', 'Fruit Salad', 'Nuts and Seeds'],
            'non-veg': ['Boiled Egg', 'Chicken Salad', 'Turkey Slice'],
            'vegan': ['Apple with Peanut Butter', 'Roasted Chickpeas', 'Almonds']
        }
    }
    
    import random
    
    plan = {
        'calories': int(target_calories),
        'breakfast': random.choice(meals_db['breakfast'][preference]),
        'lunch': random.choice(meals_db['lunch'][preference]),
        'dinner': random.choice(meals_db['dinner'][preference]),
        'snack': random.choice(meals_db['snack'][preference]),
        'macros': {
            'protein': f"{int(target_calories * 0.3 / 4)}g",
            'carbs': f"{int(target_calories * 0.4 / 4)}g",
            'fats': f"{int(target_calories * 0.3 / 9)}g"
        }
    }
    
    # Save to DB
    import json
    try:
        current_user_id = get_jwt_identity()
        new_plan = DietPlan(
            user_id=int(current_user_id),
            plan_data=json.dumps(plan),
            goal=goal
        )
        db.session.add(new_plan)
        db.session.commit()
    except Exception as e:
        print(f"Error saving diet plan: {e}")
        
    return jsonify(plan)
try:
    models = joblib.load('models/disease_prediction_models.pkl')
    symptoms_list = joblib.load('models/symptoms_list.pkl')
    print("Models loaded successfully.")
except Exception as e:
    print(f"Error loading models: {e}")
    models = None
    symptoms_list = []

# Initialize Skin Model
skin_model = SkinDiseaseModel()

# Initialize DB
with app.app_context():
    db.create_all()

# Auth Routes
@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    new_user = User(username=username, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()

    # Auto-login: Create token and set cookie
    access_token = create_access_token(identity=str(new_user.id))
    resp = jsonify({'message': 'User registered successfully', 'username': new_user.username})
    set_access_cookies(resp, access_token)

    return resp, 201

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    print(f"Login attempt for user: {username}")

    user = User.query.filter_by(username=username).first()

    if user:
        print(f"User found: {user.username}")
        if bcrypt.check_password_hash(user.password, password):
            print("Password match!")
            access_token = create_access_token(identity=str(user.id))
            resp = jsonify({'message': 'Login successful', 'username': user.username})
            set_access_cookies(resp, access_token)
            return resp
        else:
            print("Password mismatch")
    else:
        print("User not found")
    
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/auth/logout', methods=['POST'])
def logout():
    resp = jsonify({'message': 'Logout successful'})
    unset_jwt_cookies(resp)
    return resp

@app.route('/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    current_user_id = get_jwt_identity()
    user = User.query.get(int(current_user_id))
    return jsonify({'username': user.username})

@app.route('/symptoms', methods=['GET'])
@jwt_required()
def get_symptoms():
    return jsonify({'symptoms': symptoms_list})

@app.route('/predict', methods=['POST'])
@jwt_required()
def predict():
    if not models:
        return jsonify({'error': 'Models not loaded'}), 500
        
    data = request.json
    user_symptoms = data.get('symptoms', [])
    
    # Create input vector
    input_vector = [0] * len(symptoms_list)
    for symptom in user_symptoms:
        if symptom in symptoms_list:
            index = symptoms_list.index(symptom)
            input_vector[index] = 1
            
    input_vector = np.array([input_vector])
    
    results = {}
    for name, model in models.items():
        prediction = model.predict(input_vector)[0]
        # Get probability if available
        if hasattr(model, 'predict_proba'):
            probs = model.predict_proba(input_vector)[0]
            confidence = np.max(probs) * 100
        else:
            confidence = 0 # or some default
            
        results[name] = {
            'disease': prediction,
            'confidence': float(f"{confidence:.2f}")
        }
        
    # Simple logic to find the most agreed upon prediction
    predictions = [res['disease'] for res in results.values()]
    final_prediction = max(set(predictions), key=predictions.count)
    
    remedies = remedies_data.get(final_prediction, {"remedies": [], "exercises": []})

    # Save prediction if user is logged in
    try:
        current_user_id = get_jwt_identity()
        if current_user_id:
            new_prediction = Prediction(
                user_id=int(current_user_id),
                disease=final_prediction,
                symptoms=",".join(user_symptoms)
            )
            db.session.add(new_prediction)
            db.session.commit()
    except Exception as e:
        print(f"Error saving prediction: {e}")

    return jsonify({
        'predictions': results,
        'final_prediction': final_prediction,
        'remedies': remedies['remedies'],
        'exercises': remedies['exercises']
    })

@app.route('/history', methods=['GET'])
@jwt_required()
def get_history():
    current_user_id = get_jwt_identity()
    predictions = Prediction.query.filter_by(user_id=current_user_id).order_by(Prediction.date.desc()).all()
    
    history_list = []
    for pred in predictions:
        history_list.append({
            'id': pred.id,
            'disease': pred.disease,
            'date': pred.date.strftime('%Y-%m-%d %H:%M'),
            'symptoms': pred.symptoms.split(',')
        })
        
    return jsonify({'history': history_list})

@app.route('/history/<int:id>', methods=['DELETE'])
@jwt_required()
def delete_history(id):
    current_user_id = get_jwt_identity()
    prediction = Prediction.query.get_or_404(id)
    
    if prediction.user_id != int(current_user_id):
        return jsonify({'error': 'Unauthorized'}), 403
        
    db.session.delete(prediction)
    db.session.commit()
    
    return jsonify({'message': 'Prediction deleted successfully'})

@app.route('/diet-history', methods=['GET'])
@jwt_required()
def get_diet_history():
    current_user_id = get_jwt_identity()
    plans = DietPlan.query.filter_by(user_id=current_user_id).order_by(DietPlan.date.desc()).all()
    
    history_list = []
    import json
    for plan in plans:
        history_list.append({
            'id': plan.id,
            'date': plan.date.strftime('%Y-%m-%d %H:%M'),
            'goal': plan.goal,
            'plan_data': json.loads(plan.plan_data)
        })
        
    return jsonify({'history': history_list})

@app.route('/diet-history/<int:id>', methods=['DELETE'])
@jwt_required()
def delete_diet_history(id):
    current_user_id = get_jwt_identity()
    plan = DietPlan.query.get_or_404(id)
    
    if plan.user_id != int(current_user_id):
        return jsonify({'error': 'Unauthorized'}), 403
        
    db.session.delete(plan)
    db.session.commit()
    
    return jsonify({'message': 'Diet plan deleted successfully'})

@app.route('/predict-skin', methods=['POST'])
@jwt_required()
def predict_skin():
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
        
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file:
        # Save file to temp location
        filename = secure_filename(file.filename)
        upload_folder = os.path.join(app.instance_path, 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        
        # Run prediction
        results = skin_model.predict(filepath)
        
        # Clean up (optional, or keep for history)
        # os.remove(filepath) 
        
        if isinstance(results, dict) and "error" in results:
             return jsonify(results), 500
             
        # Use the top prediction
        top_result = results[0]
        
        # Save to SkinAnalysisLog
        try:
            current_user_id = get_jwt_identity()
            if current_user_id:
                new_log = SkinAnalysisLog(
                    user_id=int(current_user_id),
                    condition_name=top_result['name'],
                    probability=top_result['probability'],
                    image_path=filepath # Storing local path for now
                )
                db.session.add(new_log)
                db.session.commit()
        except Exception as e:
            print(f"Error saving skin analysis log: {e}")

        return jsonify(top_result)
    
    return jsonify({'error': 'Something went wrong'}), 500

@app.route('/profile', methods=['GET', 'POST'])
@jwt_required()
def handle_profile():
    current_user_id = get_jwt_identity()
    profile = UserProfile.query.filter_by(user_id=current_user_id).first()
    
    if request.method == 'GET':
        if not profile:
            return jsonify({})
        return jsonify({
            'age': profile.age,
            'gender': profile.gender,
            'height': profile.height,
            'weight': profile.weight,
            'blood_type': profile.blood_type,
            'allergies': profile.allergies
        })
        
    if request.method == 'POST':
        data = request.json
        if not profile:
            profile = UserProfile(user_id=int(current_user_id))
            db.session.add(profile)
            
        profile.age = data.get('age')
        profile.gender = data.get('gender')
        profile.height = data.get('height')
        profile.weight = data.get('weight')
        profile.blood_type = data.get('blood_type')
        profile.allergies = data.get('allergies')
        
        db.session.commit()
        return jsonify({'message': 'Profile updated successfully'})

@app.route('/skin-history', methods=['GET'])
@jwt_required()
def get_skin_history():
    current_user_id = get_jwt_identity()
    logs = SkinAnalysisLog.query.filter_by(user_id=current_user_id).order_by(SkinAnalysisLog.date.desc()).all()
    
    history = []
    for log in logs:
        history.append({
            'id': log.id,
            'date': log.date.strftime('%Y-%m-%d %H:%M'),
            'condition_name': log.condition_name,
            'probability': log.probability
        })
        
    return jsonify({'history': history})

@app.route('/exercise', methods=['POST'])
@jwt_required()
def log_exercise():
    data = request.json
    current_user_id = get_jwt_identity()
    
    new_log = ExerciseLog(
        user_id=int(current_user_id),
        exercise_type=data.get('exercise_type'),
        duration_minutes=int(data.get('duration_minutes')),
        calories_burnt=int(data.get('calories_burnt'))
    )
    
    db.session.add(new_log)
    db.session.commit()
    
    return jsonify({'message': 'Exercise logged successfully', 'id': new_log.id})

@app.route('/exercise/history', methods=['GET'])
@jwt_required()
def get_exercise_history():
    current_user_id = get_jwt_identity()
    # Get last 7 days
    seven_days_ago = datetime.now() - timedelta(days=7)
    logs = ExerciseLog.query.filter(
        ExerciseLog.user_id == current_user_id,
        ExerciseLog.date >= seven_days_ago
    ).order_by(ExerciseLog.date.asc()).all()
    
    history = []
    for log in logs:
        history.append({
            'id': log.id,
            'date': log.date.strftime('%Y-%m-%d'),
            'exercise_type': log.exercise_type,
            'duration_minutes': log.duration_minutes,
            'calories_burnt': log.calories_burnt
        })
        
    return jsonify({'history': history})

@app.route('/exercise/recommendations', methods=['GET'])
@jwt_required()
def get_exercise_recommendations():
    current_user_id = get_jwt_identity()
    # Try to find latest diet plan to get goal
    latest_plan = DietPlan.query.filter_by(user_id=current_user_id).order_by(DietPlan.date.desc()).first()
    
    goal = latest_plan.goal if latest_plan else 'maintain'
    
    recommendations = {
        'lose': [
            "HIIT (High Intensity Interval Training) for 20 mins",
            "Running or Jogging for 30 mins",
            "Swimming for 45 mins",
            "Jump Rope for 15 mins"
        ],
        'gain': [
            "Heavy Weight Lifting (Squats, Deadlifts, Bench Press)",
            "Resistance Band Training",
            "Calisthenics (Pushups, Pullups)",
            "Yoga for flexibility and strength"
        ],
        'maintain': [
            "Moderate Cardio (Cycling, Brisk Walking)",
            "Yoga or Pilates",
            "Light Weight Training",
            "Hiking or Sports"
        ]
    }
    
    return jsonify({'recommendations': recommendations.get(goal, recommendations['maintain'])})

@app.route('/contacts', methods=['GET', 'POST'])
@jwt_required()
def handle_contacts():
    current_user_id = get_jwt_identity()
    
    if request.method == 'GET':
        contacts = EmergencyContact.query.filter_by(user_id=current_user_id).all()
        return jsonify({
            'contacts': [{
                'id': c.id,
                'name': c.name,
                'phone': c.phone,
                'email': c.email
            } for c in contacts]
        })
        
    if request.method == 'POST':
        data = request.json
        new_contact = EmergencyContact(
            user_id=int(current_user_id),
            name=data.get('name'),
            phone=data.get('phone'),
            email=data.get('email')
        )
        db.session.add(new_contact)
        db.session.commit()
        return jsonify({'message': 'Contact added successfully', 'id': new_contact.id})

@app.route('/contacts/<int:id>', methods=['DELETE'])
@jwt_required()
def delete_contact(id):
    current_user_id = get_jwt_identity()
    contact = EmergencyContact.query.get_or_404(id)
    
    if contact.user_id != int(current_user_id):
        return jsonify({'error': 'Unauthorized'}), 403
        
    db.session.delete(contact)
    db.session.commit()
    return jsonify({'message': 'Contact deleted successfully'})

@app.route('/sos', methods=['POST'])
@jwt_required()
def send_sos():
    current_user_id = get_jwt_identity()
    data = request.json
    lat = data.get('latitude')
    lng = data.get('longitude')
    
    contacts = EmergencyContact.query.filter_by(user_id=current_user_id).all()
    
    if not contacts:
        return jsonify({'message': 'No contacts found, but SOS logged.'}), 200
        
    # Simulate sending alerts
    print(f"--- SOS ALERT ---")
    print(f"User ID: {current_user_id}")
    print(f"Location: {lat}, {lng}")
    print(f"Sending alerts to:")
    for contact in contacts:
        print(f"- {contact.name} ({contact.phone}, {contact.email})")
    print(f"-----------------")
    
    return jsonify({'message': f'SOS sent to {len(contacts)} contacts'})

@app.route('/doctors', methods=['POST'])
@jwt_required()
def find_doctors():
    data = request.json
    specialty = data.get('specialty')
    location = data.get('location')
    
    if not specialty or not location:
        return jsonify({'error': 'Specialty and location are required'}), 400
        
    query = f"{specialty} doctors near {location}"
    print(f"Searching for: {query}")
    
    # Mock data for demonstration if scraping fails or for reliability
    # In a real production app, you would use a paid API like Google Places API
    mock_doctors = [
        {
            'name': f"Dr. Smith ({specialty})",
            'address': f"123 Medical Center, {location}",
            'rating': "4.8",
            'reviews': "124 reviews",
            'timings': "Open ⋅ Closes 6PM",
            'phone': "+1 234-567-8900",
            'lat': 40.7128, # Mock lat (NYC)
            'lng': -74.0060  # Mock lng (NYC)
        },
        {
            'name': f"City {specialty} Clinic",
            'address': f"45 Health Ave, {location}",
            'rating': "4.5",
            'reviews': "89 reviews",
            'timings': "Open ⋅ Closes 8PM",
            'phone': "+1 987-654-3210",
            'lat': 40.7150,
            'lng': -74.0090
        },
        {
            'name': f"Advanced {specialty} Care",
            'address': f"789 Wellness Blvd, {location}",
            'rating': "4.9",
            'reviews': "210 reviews",
            'timings': "Closed ⋅ Opens 9AM",
            'phone': "+1 555-123-4567",
            'lat': 40.7110,
            'lng': -74.0030
        }
    ]

    try:
        import requests
        
        api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
        if not api_key or api_key == 'YOUR_API_KEY_HERE':
            print("Warning: GOOGLE_MAPS_API_KEY not set or is default.")
            # Return mock data if no key
            return jsonify({'doctors': mock_doctors})

        # Google Places Text Search API
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            'query': f"{specialty} doctors in {location}",
            'key': api_key
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if data.get('status') == 'OK':
            results = data.get('results', [])
            real_doctors = []
            
            for place in results:
                # Get details for each place (optional, but Text Search gives basic info)
                # We can use the basic info for now
                
                # Format opening hours
                opening_hours = "Not available"
                if place.get('opening_hours', {}).get('open_now'):
                    opening_hours = "Open Now"
                
                doctor = {
                    'name': place.get('name'),
                    'address': place.get('formatted_address'),
                    'rating': str(place.get('rating', 'N/A')),
                    'reviews': f"{place.get('user_ratings_total', 0)} reviews",
                    'timings': opening_hours,
                    'phone': "Phone number not available in list view", # Requires Place Details API
                    'lat': place['geometry']['location']['lat'],
                    'lng': place['geometry']['location']['lng'],
                    'place_id': place.get('place_id')
                }
                real_doctors.append(doctor)
            
            return jsonify({'doctors': real_doctors})
        else:
            print(f"Google Places API Error: {data.get('status')} - {data.get('error_message')}")
            return jsonify({'doctors': mock_doctors}) # Fallback
            
    except Exception as e:
        print(f"Error fetching doctors: {e}")
        return jsonify({'doctors': mock_doctors})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
