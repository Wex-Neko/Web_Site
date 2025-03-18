from flask import Flask, jsonify, request, render_template
import mariadb
import sqlite3
import sys
from typing import Optional, Dict, List, Tuple

app = Flask(__name__)

DB_CONFIG = {
    'mariadb': {
        'host': 'localhost',
        'port': 3306,
        'user': 'task_user',
        'password': 'task_password',
        'database': 'task_manager'
    },
    'sqlite': {
        'database': 'tasks_sqlite.db'
    }
}

in_memory_tasks: Dict[int, List[Dict]] = {}

class DatabaseConnection:
    def __init__(self, db_type: str):
        self.db_type = db_type
        self.conn = None

    def connect(self) -> Optional[object]:
        try:
            if self.db_type == 'mariadb':
                self.conn = mariadb.connect(**DB_CONFIG['mariadb'])
            elif self.db_type == 'sqlite':
                self.conn = sqlite3.connect(DB_CONFIG['sqlite']['database'])
            return self.conn
        except (mariadb.Error, sqlite3.Error) as e:
            print(f"Ошибка подключения к {self.db_type}: {e}")
            return None

    def close(self):
        if self.conn:
            self.conn.close()

def init_databases() -> bool:
    try:
        conn = mariadb.connect(
            host=DB_CONFIG['mariadb']['host'],
            port=DB_CONFIG['mariadb']['port'],
            user=DB_CONFIG['mariadb']['user'],
            password=DB_CONFIG['mariadb']['password']
        )
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS task_manager")
        conn.commit()
        conn.close()
        print("MariaDB: База данных создана или уже существует")
    except mariadb.Error as e:
        print(f"Ошибка создания MariaDB: {e}")
        return False

    mariadb_success = False
    mariadb_conn = DatabaseConnection('mariadb').connect()
    if mariadb_conn:
        try:
            cursor = mariadb_conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    task_text TEXT NOT NULL,
                    completed BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            mariadb_conn.commit()
            print("MariaDB: Таблицы созданы или уже существуют")
            mariadb_success = True
        except mariadb.Error as e:
            print(f"Ошибка создания таблиц MariaDB: {e}")
        finally:
            mariadb_conn.close()

    sqlite_success = False
    sqlite_conn = DatabaseConnection('sqlite').connect()
    if sqlite_conn:
        try:
            cursor = sqlite_conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    task_text TEXT NOT NULL,
                    completed INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')
            sqlite_conn.commit()
            print("SQLite: Таблицы созданы или уже существуют")
            sqlite_success = True
        except sqlite3.Error as e:
            print(f"Ошибка создания таблиц SQLite: {e}")
        finally:
            sqlite_conn.close()

    if not (mariadb_success or sqlite_success):
        print("Ошибка: Ни одна база данных не была инициализирована")
        return False
    return True

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/users', methods=['POST'])
def save_username():
    data = request.get_json()
    if not data or 'username' not in data:
        return jsonify({'error': 'Username is required'}), 400

    username = data['username'].strip()
    if not username:
        return jsonify({'error': 'Username cannot be empty'}), 400
    
    user_id = None
    tasks = []
    success = False
    
    for db_type in ['mariadb', 'sqlite']:
        conn = DatabaseConnection(db_type).connect()
        if not conn:
            print(f"Не удалось подключиться к {db_type}")
            continue
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            
            if not user:
                cursor.execute("INSERT INTO users (username) VALUES (?)", (username,))
                conn.commit()
                user_id = cursor.lastrowid if db_type == 'mariadb' else conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                user_id = user[0]
            
            cursor.execute("SELECT id, task_text, completed FROM tasks WHERE user_id = ?", (user_id,))
            tasks = [{'id': t[0], 'text': t[1], 'completed': bool(t[2])} for t in cursor.fetchall()]
            in_memory_tasks[user_id] = tasks
            success = True
        except (mariadb.Error, sqlite3.Error) as e:
            print(f"Ошибка в {db_type}: {e}")
        finally:
            conn.close()
    
    if not success:
        return jsonify({'error': 'All database connections failed'}), 500
    
    for db_type in ['mariadb', 'sqlite']:
        conn = DatabaseConnection(db_type).connect()
        if not conn:
            continue
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            existing_user = cursor.fetchone()
            if not existing_user:
                cursor.execute("INSERT INTO users (id, username) VALUES (?, ?)", (user_id, username))
                conn.commit()
            elif existing_user[0] != user_id:
                cursor.execute("UPDATE users SET id = ? WHERE username = ?", (user_id, username))
                conn.commit()
        except (mariadb.Error, sqlite3.Error) as e:
            print(f"Ошибка синхронизации в {db_type}: {e}")
        finally:
            conn.close()
    
    return jsonify({'user_id': user_id, 'username': username, 'tasks': tasks, 'status': 'success'})

@app.route('/api/tasks', methods=['GET', 'POST'])
def handle_tasks():
    if request.method == 'GET':
        user_id = request.args.get('user_id', type=int)
        if not user_id or user_id not in in_memory_tasks:
            return jsonify({'error': 'Invalid or missing user_id'}), 400
        return jsonify({'tasks': in_memory_tasks[user_id], 'status': 'success'})

    elif request.method == 'POST':
        data = request.get_json()
        if not data or 'user_id' not in data or 'task_text' not in data:
            return jsonify({'error': 'User ID and task text are required'}), 400

        user_id = data['user_id']
        task_text = data['task_text'].strip()
        
        if not task_text:
            return jsonify({'error': 'Task text cannot be empty'}), 400

        success = False
        for db_type in ['mariadb', 'sqlite']:
            conn = DatabaseConnection(db_type).connect()
            if not conn:
                print(f"Не удалось подключиться к {db_type}")
                continue
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
                result = cursor.fetchone()
                print(f"{db_type}: Проверка user_id={user_id}, результат={result}")
                if not result:
                    print(f"{db_type}: Пользователь с id={user_id} не найден")
                    continue

                cursor.execute("INSERT INTO tasks (user_id, task_text) VALUES (?, ?)", (user_id, task_text))
                conn.commit()
                load_tasks_to_memory(user_id, conn, db_type)
                success = True
            except (mariadb.Error, sqlite3.Error) as e:
                print(f"Ошибка добавления задачи в {db_type}: {e}")
            finally:
                conn.close()
        
        if success:
            return jsonify({'message': 'Task added successfully', 'status': 'success'})
        return jsonify({'error': 'Failed to add task to any database'}), 500

@app.route('/api/tasks/<int:task_id>', methods=['PUT', 'DELETE'])
def modify_task(task_id):
    if request.method == 'PUT':
        data = request.get_json()
        if not data or 'completed' not in data:
            return jsonify({'error': 'Completed status is required'}), 400

        success = False
        for db_type in ['mariadb', 'sqlite']:
            conn = DatabaseConnection(db_type).connect()
            if not conn:
                continue
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM tasks WHERE id = ?", (task_id,))
                result = cursor.fetchone()
                if not result:
                    return jsonify({'error': 'Task not found'}), 404
                
                user_id = result[0]
                cursor.execute("UPDATE tasks SET completed = ? WHERE id = ?", (data['completed'], task_id))
                conn.commit()
                load_tasks_to_memory(user_id, conn, db_type)
                success = True
            except (mariadb.Error, sqlite3.Error) as e:
                print(f"Ошибка обновления задачи в {db_type}: {e}")
            finally:
                conn.close()
        
        if success:
            return jsonify({'message': 'Task updated', 'status': 'success'})
        return jsonify({'error': 'Failed to update task in any database'}), 500

    elif request.method == 'DELETE':
        success = False
        for db_type in ['mariadb', 'sqlite']:
            conn = DatabaseConnection(db_type).connect()
            if not conn:
                continue
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM tasks WHERE id = ?", (task_id,))
                result = cursor.fetchone()
                if not result:
                    return jsonify({'error': 'Task not found'}), 404
                
                user_id = result[0]
                cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()
                load_tasks_to_memory(user_id, conn, db_type)
                success = True
            except (mariadb.Error, sqlite3.Error) as e:
                print(f"Ошибка удаления задачи в {db_type}: {e}")
            finally:
                conn.close()
        
        if success:
            return jsonify({'message': 'Task deleted', 'status': 'success'})
        return jsonify({'error': 'Failed to delete task in any database'}), 500

def load_tasks_to_memory(user_id: int, conn: object, db_type: str):
    cursor = conn.cursor()
    cursor.execute("SELECT id, task_text, completed FROM tasks WHERE user_id = ?", (user_id,))
    in_memory_tasks[user_id] = [{'id': t[0], 'text': t[1], 'completed': bool(t[2])} for t in cursor.fetchall()]

if __name__ == '__main__':
    if init_databases():
        app.run()
    else:
        sys.exit(1)