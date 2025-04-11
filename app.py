# Important: Keep all imports and configurations as they were in the previous version
# with the 50MB limit.

import os
import io
from datetime import datetime
# Import RequestEntityTooLarge or just handle the 413 code
from werkzeug.exceptions import RequestEntityTooLarge
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_file, abort, current_app, send_from_directory
)
from dotenv import load_dotenv
from appwrite.client import Client
from appwrite.services.storage import Storage
from appwrite.input_file import InputFile
from appwrite.exception import AppwriteException
import humanize # For nice file sizes / dates
import logging # Optional: For better logging in production

# --- NEW: Load .env ONLY if it exists (useful for local dev, ignored in Docker runtime) ---
# In production, variables should be passed directly to the container.
load_dotenv()

# --- Configuration (Read ALL from environment variables) ---
APPWRITE_ENDPOINT = os.getenv('APPWRITE_ENDPOINT', 'https://cloud.appwrite.io/v1') # Provide a default if desired
APPWRITE_PROJECT_ID = os.getenv('APPWRITE_PROJECT_ID')
APPWRITE_API_KEY = os.getenv('APPWRITE_API_KEY')
APPWRITE_BUCKET_ID = os.getenv('APPWRITE_BUCKET_ID')
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY') # MUST be set in production

# --- NEW: File Size Limit (Allow override via ENV var, default to 50MB) ---
try:
    MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', '50'))
except ValueError:
    MAX_FILE_SIZE_MB = 50 # Fallback if invalid value provided
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# --- Production Readiness Checks ---
if not all([APPWRITE_PROJECT_ID, APPWRITE_API_KEY, APPWRITE_BUCKET_ID]):
    raise ValueError("Missing required Appwrite configuration environment variables (APPWRITE_PROJECT_ID, APPWRITE_API_KEY, APPWRITE_BUCKET_ID)")
if not FLASK_SECRET_KEY:
    # Use `app.logger.critical` or raise error in production context
    # For simplicity here, we raise ValueError. In a real app, log this properly.
    raise ValueError("FLASK_SECRET_KEY environment variable is not set. This is required for production.")


# --- Flask App Setup ---
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE_BYTES

# --- Optional: Configure Basic Logging for Production ---
# Gunicorn usually handles access logs, but configure app logs if needed.
if os.getenv('FLASK_ENV') != 'development': # Only configure this way if not in dev mode
    logging.basicConfig(level=logging.INFO) # Log INFO level and above
    # You might want more sophisticated logging here (e.g., rotating file handlers)

# --- Appwrite Client Setup (remains the same) ---
client = Client()
client.set_endpoint(APPWRITE_ENDPOINT)
client.set_project(APPWRITE_PROJECT_ID)
client.set_key(APPWRITE_API_KEY)
storage = Storage(client)


# --- Helper Functions (remains the same) ---
def format_file_list(file_list):
    # (Keep the existing function)
    formatted_files = []
    for file in file_list:
        try:
            dt_object = datetime.fromisoformat(file['$createdAt'].replace('Z', '+00:00'))
            file['date_human'] = humanize.naturaltime(datetime.now(dt_object.tzinfo) - dt_object)
        except (ValueError, KeyError, TypeError) as e:
             current_app.logger.warning(f"Could not parse date '{file.get('$createdAt', 'N/A')}': {e}")
             file['date_human'] = "Unknown date" # Fallback
        try:
            file['size_human'] = humanize.naturalsize(file['sizeOriginal'], binary=True)
        except (KeyError, TypeError) as e:
            current_app.logger.warning(f"Could not get size for file '{file.get('name', 'N/A')}': {e}")
            file['size_human'] = "Unknown size" # Fallback
        formatted_files.append(file)
    return formatted_files

# --- Routes (Index, Upload, Delete, View, Download - remain the same) ---
# Keep all the route definitions (@app.route(...)) exactly as they were in the
# previous version (Bootstrap UI with 50MB limit checks).
# Make sure flash messages use appropriate categories ('danger', 'success', 'warning').

@app.route('/')
def index():
    """Lists files in the bucket."""
    try:
        result = storage.list_files(APPWRITE_BUCKET_ID)
        files = format_file_list(result['files'])
        files.sort(key=lambda x: x.get('$createdAt', ''), reverse=True)
    except AppwriteException as e:
        flash(f"Error listing files from Appwrite: {e.message} (Code: {e.code})", 'danger')
        files = []
        current_app.logger.error(f"Appwrite error listing files: {e}", exc_info=True) # Log error
    except Exception as e:
        flash(f"An unexpected error occurred while listing files.", 'danger') # Generic message
        files = []
        current_app.logger.error(f"Unexpected error listing files: {e}", exc_info=True) # Log error

    # Pass MAX_FILE_SIZE_MB to template
    return render_template('index.html', files=files, bucket_id=APPWRITE_BUCKET_ID, max_size_mb=MAX_FILE_SIZE_MB)


# --- NEW: Route to serve favicon.ico ---
@app.route('/favicon.ico')
def favicon():
    # Serve the favicon from the static directory
    # Ensure you have a 'favicon.ico' file in your 'static' folder
    return send_from_directory(os.path.join(app.root_path, 'static'),
                           'favicon.ico', mimetype='image/vnd.microsoft.icon')


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handles file uploads."""
    if 'file' not in request.files:
        flash('No file part in the request.', 'warning')
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        flash('No file selected for uploading.', 'warning')
        return redirect(url_for('index'))
    if file:
        try:
            # MAX_CONTENT_LENGTH check happens before this
            file_bytes = file.read()
            input_file = InputFile.from_bytes(file_bytes, filename=file.filename, mime_type=file.mimetype)
            storage.create_file(
                bucket_id=APPWRITE_BUCKET_ID,
                file_id='unique()',
                file=input_file
            )
            flash(f"File '{file.filename}' uploaded successfully!", 'success')
        except AppwriteException as e:
            flash(f"Error uploading file '{file.filename}': {e.message}", 'danger')
            current_app.logger.error(f"Appwrite error uploading file {file.filename}: {e}", exc_info=True)
        except Exception as e:
             flash(f"An unexpected error occurred during upload.", 'danger')
             current_app.logger.error(f"Unexpected error uploading file {file.filename}: {e}", exc_info=True)
    return redirect(url_for('index'))

@app.route('/delete/<string:file_id>', methods=['POST'])
def delete_file(file_id):
    """Deletes a specific file."""
    file_name_to_delete = request.form.get('filename', file_id)
    try:
        storage.delete_file(APPWRITE_BUCKET_ID, file_id)
        flash(f"File '{file_name_to_delete}' deleted successfully!", 'success')
    except AppwriteException as e:
        flash(f"Error deleting file '{file_name_to_delete}': {e.message}", 'danger')
        current_app.logger.error(f"Appwrite error deleting file {file_id}: {e}", exc_info=True)
    except Exception as e:
        flash(f"An unexpected error occurred during deletion.", 'danger')
        current_app.logger.error(f"Unexpected error deleting file {file_id}: {e}", exc_info=True)
    return redirect(url_for('index'))

@app.route('/view/<string:file_id>')
def view_file(file_id):
    """Provides a way to view the file inline in the browser."""
    try:
        file_meta = storage.get_file(APPWRITE_BUCKET_ID, file_id)
        file_name = file_meta['name']
        mime_type = file_meta['mimeType']
        result_bytes = storage.get_file_view(APPWRITE_BUCKET_ID, file_id)
        return send_file(
            io.BytesIO(result_bytes),
            mimetype=mime_type,
            as_attachment=False,
            download_name=file_name
       )
    except AppwriteException as e:
        current_app.logger.error(f"Appwrite error viewing file {file_id}: {e}", exc_info=True)
        if e.code == 404:
             abort(404, description=f"File not found.")
        else:
             abort(500, description=f"Error retrieving file from storage.")
    except Exception as e:
        current_app.logger.error(f"Unexpected error viewing file {file_id}: {e}", exc_info=True)
        abort(500, description="An unexpected error occurred.")


@app.route('/download/<string:file_id>')
def download_file(file_id):
    """Forces the browser to download the file."""
    try:
        file_meta = storage.get_file(APPWRITE_BUCKET_ID, file_id)
        file_name = file_meta['name']
        mime_type = file_meta.get('mimeType', 'application/octet-stream')
        result_bytes = storage.get_file_download(APPWRITE_BUCKET_ID, file_id)
        return send_file(
            io.BytesIO(result_bytes),
            mimetype=mime_type,
            as_attachment=True,
            download_name=file_name
       )
    except AppwriteException as e:
        current_app.logger.error(f"Appwrite error downloading file {file_id}: {e}", exc_info=True)
        if e.code == 404:
             abort(404, description=f"File not found.")
        else:
             abort(500, description=f"Error retrieving file from storage.")
    except Exception as e:
        current_app.logger.error(f"Unexpected error downloading file {file_id}: {e}", exc_info=True)
        abort(500, description="An unexpected error occurred.")


# --- Error Handler for Large Files (remains the same) ---
@app.errorhandler(413)
# Or @app.errorhandler(RequestEntityTooLarge)
def request_entity_too_large(error):
    """Handles errors caused by uploads exceeding the size limit."""
    flash(f"File is too large. Maximum upload size is {MAX_FILE_SIZE_MB} MB.", 'danger')
    return redirect(url_for('index'))

# --- Generic Error Handlers (Optional but Recommended) ---
@app.errorhandler(404)
def not_found_error(error):
    current_app.logger.warning(f"Not found error: {error.description} for {request.url}")
    flash(error.description or "Page not found.", 'warning')
    # Optionally render a specific 404 template
    # return render_template('404.html'), 404
    return redirect(url_for('index')) # Redirect to index for simplicity here

@app.errorhandler(500)
def internal_error(error):
    # Log the error properly here if not already done in specific routes
    current_app.logger.error(f"Internal server error: {error.description or error} for {request.url}", exc_info=True)
    flash(error.description or "An internal server error occurred. Please try again later.", 'danger')
    # Optionally render a specific 500 template
    # return render_template('500.html'), 500
    return redirect(url_for('index')) # Redirect to index for simplicity here


# --- Run the App (Removed for Production with Gunicorn) ---
# The following block is typically NOT run when using Gunicorn.
# It's mainly for local development (`python app.py`).
if __name__ == '__main__':
    print("-------------------------------------------------------")
    print(" WARNING: Running Flask development server directly.")
    print(" This is NOT suitable for production.")
    print(" Use a WSGI server like Gunicorn in production.")
    print("-------------------------------------------------------")
    # Ensure debug is False if somehow run directly in a non-dev context
    app.run(host='0.0.0.0', port=5001, debug=False)