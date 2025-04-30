from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from collections import defaultdict

app = Flask(__name__)
CORS(app)

# TMDb API key
TMDB_API_KEY = "07a0a87853e17ed0c6f7ddbfdb065737"

# Ánh xạ thể loại tiếng Việt sang tên thể loại tiếng Anh và ID của TMDb
GENRE_MAPPING = {
    "hành động": {"name": "Action", "id": 28},
    "phiêu lưu": {"name": "Adventure", "id": 12},
    "hoạt hình": {"name": "Animation", "id": 16},
    "hài": {"name": "Comedy", "id": 35},
    "tội phạm": {"name": "Crime", "id": 80},
    "tài liệu": {"name": "Documentary", "id": 99},
    "chính kịch": {"name": "Drama", "id": 18},
    "gia đình": {"name": "Family", "id": 10751},
    "giả tưởng": {"name": "Fantasy", "id": 14},
    "lịch sử": {"name": "History", "id": 36},
    "kinh dị": {"name": "Horror", "id": 27},
    "nhạc": {"name": "Music", "id": 10402},
    "bí ẩn": {"name": "Mystery", "id": 9648},
    "lãng mạn": {"name": "Romance", "id": 10749},
    "khoa học viễn tưởng": {"name": "Science Fiction", "id": 878},
    "truyền hình": {"name": "TV Movie", "id": 10770},
    "giật gân": {"name": "Thriller", "id": 53},
    "chiến tranh": {"name": "War", "id": 10752},
    "miền tây": {"name": "Western", "id": 37},
}

# Ánh xạ ngữ cảnh ban đầu
CONTEXT_MAPPING = {
    "bắn nhau": ["hành động"],
    "đánh nhau": ["hành động"],
    "nhà ma": ["kinh dị"],
    "ma quỷ": ["kinh dị"],
    "tình yêu": ["lãng mạn"],
    "hài hước": ["hài"],
    "chiến tranh": ["chiến tranh", "lịch sử"],
    "vũ trụ": ["khoa học viễn tưởng"],
    "siêu anh hùng": ["hành động", "giả tưởng"],
    "trinh thám": ["bí ẩn", "tội phạm"],
    "cướp bóc": ["tội phạm", "hành động"],
}

# Biến toàn cục để lưu trữ ánh xạ học được (thay vì dùng file)
LEARNED_CONTEXT_MAPPING = defaultdict(list)

# Kết hợp ánh xạ ban đầu và ánh xạ học được
def get_combined_context_mapping():
    combined = defaultdict(list)
    for key, genres in CONTEXT_MAPPING.items():
        combined[key].extend(genres)
    for key, genres in LEARNED_CONTEXT_MAPPING.items():
        combined[key].extend(genres)
    return combined

@app.route('/generate', methods=['POST'])
def generate_recommendations():
    print('Received request:', request.get_json())
    data = request.get_json()
    if not data or 'prompt' not in data:
        print('Error: Prompt is missing in request body')
        return jsonify({'error': 'Prompt is required'}), 400

    prompt = data.get('prompt')
    print(f"Processing prompt: {prompt}")

    # Tiền xử lý prompt
    prompt = prompt.strip().lower()
    tokens = prompt.split()
    print(f"Tokens after splitting: {tokens}")

    # Trích xuất năm nếu có
    year = None
    for token in tokens:
        if token.isdigit() and len(token) == 4 and 1900 <= int(token) <= 2025:
            year = token
            tokens.remove(token)
            break

    # Trích xuất thể loại và ngữ cảnh
    combined_context_mapping = get_combined_context_mapping()
    genres = set()
    context_keywords = []

    # Tìm thể loại trực tiếp từ GENRE_MAPPING
    for token in tokens[:]:
        token_lower = token.lower()
        if token_lower in GENRE_MAPPING:
            genres.add(GENRE_MAPPING[token_lower]["id"])
            tokens.remove(token)
        elif token_lower in combined_context_mapping:
            context_keywords.append(token_lower)
            for genre in combined_context_mapping[token_lower]:
                if genre in GENRE_MAPPING:
                    genres.add(GENRE_MAPPING[genre]["id"])
            tokens.remove(token)

    # Loại bỏ từ khóa không cần thiết
    tokens = [token for token in tokens if token not in ['gợi ý', 'phim', 'một', 'của', 'về']]

    # Tạo query tìm kiếm
    query = ' '.join(tokens).strip()
    if not query and not year and not genres:
        return jsonify({'error': 'Prompt does not contain enough information to search'}), 400

    try:
        # Tìm kiếm phim trên TMDb
        movies = []
        if query:
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}"
            if year:
                search_url += f"&year={year}"
            response = requests.get(search_url)
            search_results = response.json()
            if 'results' in search_results and search_results['results']:
                movies.extend(search_results['results'])

        # Nếu có thể loại, tìm kiếm thêm bằng discover/movie
        if genres:
            genre_ids = ','.join(map(str, genres))
            discover_url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&with_genres={genre_ids}"
            if year:
                discover_url += f"&primary_release_year={year}"
            response = requests.get(discover_url)
            discover_results = response.json()
            if 'results' in discover_results and discover_results['results']:
                movies.extend(discover_results['results'])

        if not movies:
            return jsonify({'error': 'No movies found matching the prompt'}), 404

        # Loại bỏ trùng lặp và lấy tối đa 3 phim
        seen_ids = set()
        unique_movies = []
        for movie in movies:
            if movie['id'] not in seen_ids:
                seen_ids.add(movie['id'])
                unique_movies.append(movie)
        movies = unique_movies[:3]

        # Học từ ngữ cảnh (nếu có context_keywords)
        if context_keywords and genres:
            for keyword in context_keywords:
                for genre_id in genres:
                    genre_name = next((name for name, info in GENRE_MAPPING.items() if info["id"] == genre_id), None)
                    if genre_name and genre_name not in LEARNED_CONTEXT_MAPPING[keyword]:
                        LEARNED_CONTEXT_MAPPING[keyword].append(genre_name)

        # Lấy thông tin chi tiết của từng phim
        results = []
        for movie in movies:
            movie_id = movie['id']
            details_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=en-US"
            details_response = requests.get(details_url)
            movie_details = details_response.json()

            title = movie_details.get('title', 'Unknown')
            genres = [genre['id'] for genre in movie_details.get('genres', [])]
            release_date = movie_details.get('release_date', '')
            year = release_date[:4] if release_date else 'Unknown'
            overview = movie_details.get('overview', 'No description available.')
            poster_path = movie_details.get('poster_path', '')
            vote_average = movie_details.get('vote_average', 0.0)

            formatted_result = (
                f"Tên phim: {title}\n"
                f"Thể loại: {genres}\n"
                f"Năm: {year}\n"
                f"Mô tả: {overview}\n"
                f"Hình ảnh: https://image.tmdb.org/t/p/w200{poster_path}\n"
                f"Điểm: {vote_average}\n"
                f"---"
            )
            results.append(formatted_result)

        final_result = '\n'.join(results)
        print(f"Found movies:\n{final_result}")
        return jsonify({'generated_text': final_result})
    except Exception as e:
        print(f"Error during movie search: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/describe', methods=['POST'])
def describe_movie():
    print('Received request:', request.get_json())
    data = request.get_json()
    if not data or 'description' not in data:
        print('Error: Description is missing in request body')
        return jsonify({'error': 'Description is required'}), 400

    description = data.get('description')
    print(f"Processing description: {description}")

    # Tiền xử lý mô tả
    description = description.strip().lower()
    tokens = description.split()
    print(f"Tokens after splitting: {tokens}")

    # Trích xuất năm nếu có
    year = None
    for token in tokens:
        if token.isdigit() and len(token) == 4 and 1900 <= int(token) <= 2025:
            year = token
            tokens.remove(token)
            break

    # Trích xuất thể loại và ngữ cảnh
    combined_context_mapping = get_combined_context_mapping()
    genres = set()
    context_keywords = []

    # Tìm thể loại và ngữ cảnh
    for token in tokens[:]:
        token_lower = token.lower()
        if token_lower in GENRE_MAPPING:
            genres.add(GENRE_MAPPING[token_lower]["id"])
            tokens.remove(token)
        elif token_lower in combined_context_mapping:
            context_keywords.append(token_lower)
            for genre in combined_context_mapping[token_lower]:
                if genre in GENRE_MAPPING:
                    genres.add(GENRE_MAPPING[genre]["id"])
            tokens.remove(token)

    # Loại bỏ từ khóa không cần thiết
    tokens = [token for token in tokens if token not in ['phim', 'một', 'của', 'về']]

    # Tạo query tìm kiếm
    query = ' '.join(tokens).strip()
    if not query and not year and not genres:
        return jsonify({'error': 'Description does not contain enough information to search'}), 400

    try:
        # Tìm kiếm phim trên TMDb
        movies = []
        if query:
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}"
            if year:
                search_url += f"&year={year}"
            response = requests.get(search_url)
            search_results = response.json()
            if 'results' in search_results and search_results['results']:
                movies.extend(search_results['results'])

        # Nếu có thể loại, tìm kiếm thêm bằng discover/movie
        if genres:
            genre_ids = ','.join(map(str, genres))
            discover_url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&with_genres={genre_ids}"
            if year:
                discover_url += f"&primary_release_year={year}"
            response = requests.get(discover_url)
            discover_results = response.json()
            if 'results' in discover_results and discover_results['results']:
                movies.extend(discover_results['results'])

        if not movies:
            return jsonify({'error': 'No movies found matching the description'}), 404

        # Loại bỏ trùng lặp và lấy tối đa 3 phim
        seen_ids = set()
        unique_movies = []
        for movie in movies:
            if movie['id'] not in seen_ids:
                seen_ids.add(movie['id'])
                unique_movies.append(movie)
        movies = unique_movies[:3]

        # Học từ ngữ cảnh (nếu có context_keywords)
        if context_keywords and genres:
            for keyword in context_keywords:
                for genre_id in genres:
                    genre_name = next((name for name, info in GENRE_MAPPING.items() if info["id"] == genre_id), None)
                    if genre_name and genre_name not in LEARNED_CONTEXT_MAPPING[keyword]:
                        LEARNED_CONTEXT_MAPPING[keyword].append(genre_name)

        # Trả về danh sách tiêu đề phim
        movie_titles = [movie['title'] for movie in movies]
        result = "\n".join([f"{i+1}. {title}" for i, title in enumerate(movie_titles)])
        print(f"Found movies: {result}")
        return jsonify({'generated_text': result})
    except Exception as e:
        print(f"Error during description processing: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Vercel expects a WSGI callable named `app`
app = app
