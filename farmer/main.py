from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from bson.objectid import ObjectId
from bson.errors import InvalidId
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

mongo = PyMongo(app)

# Helper functions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

def validate_user_session():
    """Validate user session and return user_id if valid"""
    if 'user_id' not in session:
        return None
    
    try:
        return ObjectId(session['user_id'])
    except (InvalidId, TypeError):
        session.clear()
        return None

# Routes
@app.route('/')
def index():
    try:
        featured_products = list(mongo.db.products.find().limit(8))
        top_farmers = list(mongo.db.users.find({'user_type': 'farmer'}).limit(4))
        return render_template('index.html', 
                            featured_products=featured_products,
                            top_farmers=top_farmers)
    except Exception as e:
        app.logger.error(f"Error loading index: {str(e)}")
        flash('Error loading page', 'error')
        return render_template('index.html', featured_products=[], top_farmers=[])

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        form_data = request.form.to_dict()
        
        # Validate required fields
        required_fields = ['name', 'email', 'password', 'user_type']
        if not all(field in form_data for field in required_fields):
            flash('Please fill all required fields', 'error')
            return redirect(url_for('register'))
        
        try:
            # Check if user exists
            existing_user = mongo.db.users.find_one({'email': form_data['email']})
            if existing_user:
                flash('Email already exists', 'error')
                return redirect(url_for('register'))
            
            # Hash password
            form_data['password'] = generate_password_hash(form_data['password'])
            form_data['created_at'] = datetime.utcnow()
            
            # Handle farmer registration
            if form_data['user_type'] == 'farmer':
                form_data['farm_name'] = form_data.get('farm_name', '')
                form_data['location'] = {
                    'address': form_data.get('address', ''),
                    'city': form_data.get('city', ''),
                    'state': form_data.get('state', ''),
                    'zipcode': form_data.get('zipcode', ''),
                    'coordinates': {
                        'lat': float(form_data.get('lat', 0)),
                        'lng': float(form_data.get('lng', 0))
                    }
                }
            
            # Insert user
            mongo.db.users.insert_one(form_data)
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        
        except Exception as e:
            app.logger.error(f"Registration error: {str(e)}")
            flash('Registration failed. Please try again.', 'error')
            return redirect(url_for('register'))
    
    return render_template('auth/register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Please enter both email and password', 'error')
            return redirect(url_for('login'))
        
        try:
            user = mongo.db.users.find_one({'email': email})
            if user and check_password_hash(user['password'], password):
                session['user_id'] = str(user['_id'])
                session['user_type'] = user['user_type']
                session['name'] = user.get('name', 'User')
                
                flash('Login successful!', 'success')
                return redirect(url_for('dashboard'))
            
            flash('Invalid email or password', 'error')
        
        except Exception as e:
            app.logger.error(f"Login error: {str(e)}")
            flash('Login failed. Please try again.', 'error')
    
    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    user_id = validate_user_session()
    if not user_id:
        flash('Please login to access dashboard', 'warning')
        return redirect(url_for('login'))
    
    try:
        if session['user_type'] == 'farmer':
            products = list(mongo.db.products.find({'farmer_id': user_id}))
            orders = list(mongo.db.orders.find({'farmer_id': user_id}))
            return render_template('farmers/dashboard.html', products=products, orders=orders)
        else:
            orders = list(mongo.db.orders.find({'customer_id': user_id}))
            return render_template('customers/dashboard.html', orders=orders)
    except Exception as e:
        app.logger.error(f"Dashboard error: {str(e)}")
        flash('Error loading dashboard', 'error')
        return redirect(url_for('index'))

@app.route('/products')
def product_list():
    category = request.args.get('category')
    query = {}
    if category:
        query['category'] = category
    
    try:
        products = list(mongo.db.products.find(query))
        return render_template('products/list.html', products=products)
    except Exception as e:
        app.logger.error(f"Product list error: {str(e)}")
        flash('Error loading products', 'error')
        return render_template('products/list.html', products=[])

@app.route('/products/<product_id>')
def product_detail(product_id):
    try:
        product = mongo.db.products.find_one({'_id': ObjectId(product_id)})
        if not product:
            flash('Product not found', 'error')
            return redirect(url_for('product_list'))
        
        farmer = mongo.db.users.find_one({'_id': product['farmer_id']})
        return render_template('products/detail.html', product=product, farmer=farmer)
    except (InvalidId, TypeError):
        flash('Invalid product ID', 'error')
        return redirect(url_for('product_list'))
    except Exception as e:
        app.logger.error(f"Product detail error: {str(e)}")
        flash('Error loading product', 'error')
        return redirect(url_for('product_list'))

@app.route('/products/new', methods=['GET', 'POST'])
def add_product():
    user_id = validate_user_session()
    if not user_id or session.get('user_type') != 'farmer':
        flash('Please login as a farmer to add products', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Validate form data
        required_fields = ['name', 'category', 'price', 'quantity', 'description']
        if not all(field in request.form for field in required_fields):
            flash('Please fill all required fields', 'error')
            return redirect(request.url)
        
        try:
            form_data = {
                'name': request.form['name'],
                'category': request.form['category'],
                'price': float(request.form['price']),
                'quantity': int(request.form['quantity']),
                'description': request.form['description'],
                'farmer_id': user_id,
                'created_at': datetime.utcnow(),
                'is_organic': 'is_organic' in request.form
            }
        except (ValueError, KeyError) as e:
            flash('Invalid price or quantity', 'error')
            return redirect(request.url)
        
        # Process file upload
        if 'image' not in request.files:
            flash('No file was submitted', 'error')
            return redirect(request.url)
            
        file = request.files['image']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            try:
                # Create unique filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                original_filename = secure_filename(file.filename)
                filename = f"{timestamp}_{original_filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # Save file
                file.save(filepath)
                
                # Set permissions
                os.chmod(filepath, 0o644)
                
                # Store URL
                form_data['image_url'] = url_for('static', filename=f'uploads/{filename}')
                
                # Save to database
                mongo.db.products.insert_one(form_data)
                flash('Product added successfully!', 'success')
                return redirect(url_for('dashboard'))
                
            except Exception as e:
                app.logger.error(f"File upload error: {str(e)}")
                flash('Error saving product image', 'error')
                return redirect(request.url)
        else:
            flash('Allowed file types: png, jpg, jpeg, gif', 'error')
            return redirect(request.url)

    return render_template('products/create.html')

@app.route('/update_profile_picture', methods=['POST'])
def update_profile_picture():
    user_id = validate_user_session()
    if not user_id:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))

    # Check if the post request has the file part
    if 'profile_picture' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('profile'))

    file = request.files['profile_picture']
    
    # If user does not select file, browser submits empty file
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('profile'))

    if file and allowed_file(file.filename):
        try:
            # Create secure filename and ensure unique
            filename = secure_filename(file.filename)
            unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            
            # Ensure upload folder exists
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            
            # Save file
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(save_path)
            
            # Set permissions (0o644 = owner read/write, others read)
            os.chmod(save_path, 0o644)
            
            # Generate URL relative to static folder
            image_url = url_for('static', filename=f'uploads/{unique_filename}')
            
            # Update user in database
            mongo.db.users.update_one(
                {'_id': user_id},
                {'$set': {'image_url': image_url}}
            )
            
            flash('Profile picture updated successfully!', 'success')
        except Exception as e:
            app.logger.error(f"Error uploading profile picture: {str(e)}")
            flash('Error uploading profile picture', 'error')
    else:
        flash('Allowed file types are: png, jpg, jpeg, gif', 'error')
    
    return redirect(url_for('profile'))

@app.route('/update_social_links', methods=['POST'])
def update_social_links():
    user_id = validate_user_session()
    if not user_id:
        return redirect(url_for('login'))

    try:
        social_links = {
            'facebook': request.form.get('facebook'),
            'twitter': request.form.get('twitter'),
            'instagram': request.form.get('instagram'),
            'youtube': request.form.get('youtube')
        }

        # Remove empty values
        social_links = {k: v for k, v in social_links.items() if v}
        
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': {'social_links': social_links}}
        )
        flash('Social links updated!', 'success')
    except Exception as e:
        app.logger.error(f"Social links error: {str(e)}")
        flash('Failed to update social links', 'error')
    
    return redirect(url_for('profile'))

@app.route('/change_password', methods=['POST'])
def change_password():
    user_id = validate_user_session()
    if not user_id:
        return redirect(url_for('login'))

    try:
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('profile'))

        user = mongo.db.users.find_one({'_id': user_id})
        if not user or not check_password_hash(user['password'], current_password):
            flash('Current password is incorrect', 'error')
            return redirect(url_for('profile'))

        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': {'password': generate_password_hash(new_password)}}
        )
        flash('Password updated successfully!', 'success')
    except Exception as e:
        app.logger.error(f"Password change error: {str(e)}")
        flash('Failed to change password', 'error')
    
    return redirect(url_for('profile'))

@app.route('/profile')
def profile():
    try:
        app.logger.debug("Entering profile route")
        
        # Debug session
        app.logger.debug(f"Session data: {dict(session)}")
        
        # Validate session
        if 'user_id' not in session:
            app.logger.warning("No user_id in session")
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        
        # Convert to ObjectId
        try:
            user_id = ObjectId(session['user_id'])
            app.logger.debug(f"Converted user_id to ObjectId: {user_id}")
        except (InvalidId, TypeError) as e:
            app.logger.error(f"Invalid session ID: {str(e)}")
            session.clear()
            flash('Session expired', 'error')
            return redirect(url_for('login'))
        
        # Fetch user with defensive programming
        user = mongo.db.users.find_one(
            {'_id': user_id},
            {
                'name': 1,
                'email': 1,
                'phone': 1,
                'farm_name': 1,
                'location': 1,
                'image_url': 1,
                'social_links': 1,
                'description': 1,
                'user_type': 1
            }
        )
        
        app.logger.debug(f"User found: {bool(user)}")
        
        if not user:
            app.logger.error(f"User not found for ID: {user_id}")
            session.clear()
            flash('Account not found', 'error')
            return redirect(url_for('register'))
        
        # Convert ObjectId to string for template
        user['_id'] = str(user['_id'])
        
        # Set safe defaults
        user.setdefault('location', {
            'address': '',
            'city': '',
            'state': '',
            'zipcode': ''
        })
        user.setdefault('social_links', {})
        user.setdefault('description', '')
        
        # Set default images
        if not user.get('image_url'):
            if user.get('user_type') == 'farmer':
                user['image_url'] = url_for('static', filename='images/default-farmer.jpg')
            else:
                user['image_url'] = url_for('static', filename='images/default-profile.png')
        
        app.logger.debug(f"Processed user data: {user}")
        
        # Determine template
        template = 'farmers/profile.html' if user.get('user_type') == 'farmer' else 'customers/profile.html'
        return render_template(template, user=user)
        
    except Exception as e:
        app.logger.error(f"Profile error: {str(e)}", exc_info=True)
        flash('Failed to load profile. Please try again.', 'error')
        return redirect(url_for('dashboard'))
    
    
if __name__ == '__main__':
    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Ensure static images directory exists
    os.makedirs('static/images', exist_ok=True)
    
    app.run(debug=app.config.get('DEBUG', False))