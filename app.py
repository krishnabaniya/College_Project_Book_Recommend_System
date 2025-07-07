from flask import Flask, render_template, request, redirect, session,url_for, flash
from models import db, User
from werkzeug.security import generate_password_hash, check_password_hash
import pickle
from flask_migrate import Migrate
import pandas as pd

app = Flask(__name__)
app.secret_key = 'my_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
migrate = Migrate(app, db)

# Load collaborative filtering data
popular_df = pickle.load(open('popular.pkl', 'rb'))         # Data for popular book display
pt = pickle.load(open('pt.pkl', 'rb'))                       # Pivot table for recommendations
books = pickle.load(open('books.pkl', 'rb'))                 # Book metadata for collab filtering
similarity_scores = pickle.load(open('similarity_scores.pkl', 'rb'))  # Cosine similarity matrix

# Load top-rated books for review section
with open('top_books.pkl', 'rb') as file:
    top_books = pickle.load(file)                            # Top-rated books (your review section)

# Load content-based filtering data
content_similarity = pickle.load(open('content_similarity.pkl', 'rb'))  # Cosine sim for content
books_content = pickle.load(open('books_content.pkl', 'rb'))            # Book metadata for content


# Home route
@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('index.html',
        book_name=list(popular_df['Book-Title'].values),
        author=list(popular_df['Book-Author'].values),
        image=list(popular_df['Image-URL-M'].values),
        votes=list(popular_df['num_ratings'].values),
        rating=list(popular_df['avg_rating'].values)
    )

@app.route('/preferences', methods=['GET', 'POST'])
def preferences():
    if 'user_id' not in session:
        return redirect('/login')

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        selected = request.form.getlist('preferences')
        user.preferences = ', '.join(selected)
        db.session.commit()
        return redirect('/')
    
    user_prefs = user.preferences.split(', ') if user.preferences else []
    return render_template('preferences.html', user_prefs=user_prefs)

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        first_name = request.form.get('first_name')
        middle_name = request.form.get('middle_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        dob = request.form.get('dob')

        if User.query.filter_by(username=username).first():
            return "Username already exists!"
        
        new_user = User(
            username=username,
            password=password,
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
            email=email,
            dob=dob
        )
        db.session.add(new_user)
        db.session.commit()
        session['user_id'] = new_user.id
        return redirect('/preferences')  
    
    return render_template('register.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            return redirect('/')
        return "Invalid credentials!"
    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect('/login')

# Recommend UI with genre filter
@app.route('/recommend', methods=['GET'])
def recommend_ui():
    if 'user_id' not in session:
        return redirect('/login')

    data = []

    return render_template('recommend.html', data=data)


# Helper: normalize scores between 0 and 1
def normalize(scores):
    min_score = min(scores)
    max_score = max(scores)
    return [(s - min_score) / (max_score - min_score) if max_score != min_score else 0 for s in scores]

# Recommend logic with fuzzy matching and hybrid filtering
@app.route('/recommend_books', methods=['POST'])
def recommend():
    if 'user_id' not in session:
        return redirect('/login')

    from fuzzywuzzy import process

    user_input = request.form.get('user_input').strip().lower()
    normalized_titles = [title.lower().strip() for title in pt.index]

    # Fuzzy match: get the closest title from pt index
    match, score = process.extractOne(user_input, normalized_titles)

    if score < 60:
        return render_template('recommend.html', error="❌ No similar book title found. Try a different keyword.")

    # Use matched title for index lookup
    index = normalized_titles.index(match)

    # Collaborative filtering scores
    collab_scores = list(enumerate(similarity_scores[index]))

    # Content-based filtering scores
    content_titles = books_content['Book-Title'].str.lower().str.strip().tolist()
    if match not in content_titles:
        return render_template('recommend.html', error="❌ Book not available for content similarity.")

    content_index = content_titles.index(match)
    content_scores = list(enumerate(content_similarity[content_index]))

    # Normalize both scores
    collab_values = [x[1] for x in collab_scores]
    content_values = [x[1] for x in content_scores]

    collab_norm = normalize(collab_values)
    content_norm = normalize(content_values)

    # Combine scores with weighted average (hybrid)
    hybrid_scores = []
    for i in range(len(collab_scores)):
        combined_score = 0.6 * collab_norm[i] + 0.4 * content_norm[i]
        hybrid_scores.append((i, combined_score))

    # Get top 5 recommendations excluding the book itself
    hybrid_scores = sorted(hybrid_scores, key=lambda x: x[1], reverse=True)[1:6]

    data = []
    for i in hybrid_scores:
        title = pt.index[i[0]]
        title_clean = title.strip().lower()
        temp_df = books_content[books_content['Book-Title'].str.lower().str.strip() == title_clean]
        if not temp_df.empty:
            book_info = temp_df.drop_duplicates('Book-Title').iloc[0]
            image_url = book_info['Image-URL-M'] if book_info['Image-URL-M'] else 'https://via.placeholder.com/150'
            data.append([book_info['Book-Title'], book_info['Book-Author'], image_url])

    return render_template('recommend.html', data=data)

@app.route("/search")
def search():
    query = request.args.get("query", "").lower()
    if not query:
        flash("Please enter a search term.", "warning")
        return redirect(url_for("home"))  # fixed

    # Load books dataset
    books_df = pd.read_pickle("books.pkl")  # or load from CSV if you don't use pickle

    # Perform search on title or author
    results = books_df[
        books_df['Book-Title'].str.lower().str.contains(query) |
        books_df['Book-Author'].str.lower().str.contains(query)
    ]

    if results.empty:
        flash("No books found for your search.", "info")
        return redirect(url_for("home"))  # fixed

    return render_template(
        "search_results.html",
        book_name=results['Book-Title'].tolist(),
        author=results['Book-Author'].tolist(),
        image=results['Image-URL-M'].tolist(),
        rating=results['avg_rating'].tolist() if 'avg_rating' in results else [0]*len(results),
        votes=results['num_ratings'].tolist() if 'num_ratings' in results else [0]*len(results),
        query=query
    )

@app.route('/genre/<name>')
def genre(name):
    if 'user_id' not in session:
        return redirect('/login')

    # Filter books by genre
    if 'Genre' in books_content.columns:
        genre_books = books_content[books_content['Genre'].str.lower() == name.lower()]
    else:
        genre_books = books_content.copy()
        genre_books['Genre'] = 'Unknown'
        genre_books = genre_books[genre_books['Genre'].str.lower() == name.lower()]

    if genre_books.empty:
        return render_template('recommend.html', data=[], genre=name, error=f"No books found for genre: {name}")

    genre_books = genre_books[['Book-Title', 'Book-Author', 'Image-URL-M']].drop_duplicates('Book-Title')

    data = [
        [row['Book-Title'], row['Book-Author'], row['Image-URL-M']]
        for _, row in genre_books.iterrows()
    ]

    return render_template('recommend.html', data=data, genre=name)


# Load preprocessed data once
books_content = pickle.load(open('books_content.pkl', 'rb'))  # Contains 'avg_rating', 'num_ratings', 'Genre'
popular_df = pickle.load(open('popular.pkl', 'rb'))  # top rated books filtered already

@app.route('/reviews')
def reviews():
    # Load top_books.pkl or prepare the DataFrame in memory beforehand
    with open('top_books.pkl', 'rb') as f:
        books_list = pickle.load(f)
    
    # Pagination parameters
    page = int(request.args.get('page', 1))
    per_page = 10
    start = (page - 1) * per_page
    end = start + per_page

    paginated_books = books_list[start:end]
    has_next = end < len(books_list)

    return render_template(
        'reviews.html',
        books=paginated_books,
        page=page,
        has_next=has_next
    )

@app.route('/genres')
def genres_filter():
    # Pass all books to the template for filtering
    books = load_books_data()  # Your function to get books data
    return render_template('genres.html', books=books)


@app.route('/about')
def about():
    return render_template('about.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
