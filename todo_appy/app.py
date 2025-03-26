from flask import Flask, jsonify, request, render_template
import mariadb
import sqlite3
import sys
from typing import Optional, Dict, List, Tuple

# Инициализация Flask-приложения
app = Flask(__name__)

# Конфигурация баз данных (MariaDB и SQLite)
DB_CONFIG = {
    'mariadb': {
        'host': 'localhost',         # Адрес сервера MariaDB
        'port': 3306,               # Порт для подключения к MariaDB
        'user': 'kns',              # Имя пользователя MariaDB (замените на своё)
        'password': '172563',       # Пароль пользователя MariaDB (замените на свой)
        'database': 'task_manager'  # Название базы данных
    },
    'sqlite': {
        'database': 'tasks_sqlite.db'  # Путь к файлу базы данных SQLite
    }
}

# Словарь для хранения задач в памяти (ключ - ID пользователя, значение - список задач)
in_memory_tasks: Dict[int, List[Dict]] = {}

# Класс для управления подключением к базе данных
class DatabaseConnection:
    def __init__(self, db_type: str):
        self.db_type = db_type  # Тип базы данных ('mariadb' или 'sqlite')
        self.conn = None        # Переменная для хранения соединения

    # Метод для подключения к базе данных
    def connect(self) -> Optional[object]:
        try:
            if self.db_type == 'mariadb':
                self.conn = mariadb.connect(**DB_CONFIG['mariadb'])  # Подключение к MariaDB
            elif self.db_type == 'sqlite':
                self.conn = sqlite3.connect(DB_CONFIG['sqlite']['database'])  # Подключение к SQLite
            return self.conn
        except (mariadb.Error, sqlite3.Error) as e:
            print(f"Ошибка подключения к {self.db_type}: {e}")  # Вывод ошибки при неудаче
            return None

    # Метод для закрытия соединения с базой данных
    def close(self):
        if self.conn:
            self.conn.close()

# Функция инициализации баз данных
def init_databases() -> bool:
    # Попытка создания базы данных MariaDB
    try:
        conn = mariadb.connect(
            host=DB_CONFIG['mariadb']['host'],
            port=DB_CONFIG['mariadb']['port'],
            user=DB_CONFIG['mariadb']['user'],      
            password=DB_CONFIG['mariadb']['password']
        )
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS task_manager")  # Создание базы данных, если её нет
        conn.commit()
        conn.close()
        print("MariaDB: База данных создана или уже существует")
    except mariadb.Error as e:
        print(f"Ошибка создания MariaDB: {e}")
        return False

    # Создание таблиц в MariaDB
    mariadb_success = False
    mariadb_conn = DatabaseConnection('mariadb').connect()
    if mariadb_conn:
        try:
            cursor = mariadb_conn.cursor()
            # Создание таблицы users (пользователи)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,         # Уникальный ID с автоинкрементом
                    username VARCHAR(255) UNIQUE NOT NULL      # Имя пользователя, уникальное
                )
            ''')
            # Создание таблицы tasks (задачи)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,         # Уникальный ID задачи
                    user_id INT NOT NULL,                      # ID пользователя (внешний ключ)
                    task_text TEXT NOT NULL,                   # Текст задачи
                    completed BOOLEAN DEFAULT FALSE,           # Статус выполнения (по умолчанию FALSE)
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE  # Связь с таблицей users
                )
            ''')
            mariadb_conn.commit()
            print("MariaDB: Таблицы созданы или уже существуют")
            mariadb_success = True
        except mariadb.Error as e:
            print(f"Ошибка создания таблиц MariaDB: {e}")
        finally:
            mariadb_conn.close()

    # Создание таблиц в SQLite
    sqlite_success = False
    sqlite_conn = DatabaseConnection('sqlite').connect()
    if sqlite_conn:
        try:
            cursor = sqlite_conn.cursor()
            # Создание таблицы users (пользователи)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,     # Уникальный ID с автоинкрементом
                    username TEXT UNIQUE NOT NULL             # Имя пользователя, уникальное
                )
            ''')
            # Создание таблицы tasks (задачи)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,     # Уникальный ID задачи
                    user_id INTEGER NOT NULL,                 # ID пользователя (внешний ключ)
                    task_text TEXT NOT NULL,                  # Текст задачи
                    completed INTEGER DEFAULT 0,              # Статус выполнения (0 - не выполнено)
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE  # Связь с таблицей users
                )
            ''')
            sqlite_conn.commit()
            print("SQLite: Таблицы созданы или уже существуют")
            sqlite_success = True
        except sqlite3.Error as e:
            print(f"Ошибка создания таблиц SQLite: {e}")
        finally:
            sqlite_conn.close()

    # Проверка успешности инициализации хотя бы одной базы данных
    if not (mariadb_success or sqlite_success):
        print("Ошибка: Ни одна база данных не была инициализирована")
        return False
    return True

# Главная страница приложения
@app.route('/')
def index():
    return render_template('index.html')  # Отображение HTML-шаблона index.html

# Маршрут для сохранения имени пользователя и получения его задач
@app.route('/api/users', methods=['POST'])
def save_username():
    data = request.get_json()  # Получение JSON-данных из запроса
    if not data or 'username' not in data:
        return jsonify({'error': 'Username is required'}), 400  # Ошибка, если имя пользователя отсутствует

    username = data['username'].strip()  # Удаление лишних пробелов
    if not username:
        return jsonify({'error': 'Username cannot be empty'}), 400  # Ошибка, если имя пустое
    
    user_id = None
    tasks = []
    success = False
    
    # Попытка работы с обеими базами данных
    for db_type in ['mariadb', 'sqlite']:
        conn = DatabaseConnection(db_type).connect()
        if not conn:
            print(f"Не удалось подключиться к {db_type}")
            continue
        try:
            cursor = conn.cursor()
            # Проверка, существует ли пользователь
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            
            if not user:
                # Создание нового пользователя, если его нет
                cursor.execute("INSERT INTO users (username) VALUES (?)", (username,))
                conn.commit()
                user_id = cursor.lastrowid if db_type == 'mariadb' else conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                user_id = user[0]
            
            # Получение задач пользователя
            cursor.execute("SELECT id, task_text, completed FROM tasks WHERE user_id = ?", (user_id,))
            tasks = [{'id': t[0], 'text': t[1], 'completed': bool(t[2])} for t in cursor.fetchall()]
            in_memory_tasks[user_id] = tasks  # Сохранение задач в память
            success = True
        except (mariadb.Error, sqlite3.Error) as e:
            print(f"Ошибка в {db_type}: {e}")
        finally:
            conn.close()
    
    if not success:
        return jsonify({'error': 'All database connections failed'}), 500  # Ошибка, если обе базы недоступны
    
    # Синхронизация данных между базами
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
    
    # Возврат успешного ответа с данными пользователя и задачами
    return jsonify({'user_id': user_id, 'username': username, 'tasks': tasks, 'status': 'success'})

# Маршрут для обработки задач (получение и добавление)
@app.route('/api/tasks', methods=['GET', 'POST'])
def handle_tasks():
    if request.method == 'GET':
        user_id = request.args.get('user_id', type=int)  # Получение user_id из параметров запроса
        if not user_id or user_id not in in_memory_tasks:
            return jsonify({'error': 'Invalid or missing user_id'}), 400  # Ошибка, если ID некорректен
        return jsonify({'tasks': in_memory_tasks[user_id], 'status': 'success'})  # Возврат задач из памяти

    elif request.method == 'POST':
        data = request.get_json()  # Получение данных из POST-запроса
        if not data or 'user_id' not in data or 'task_text' not in data:
            return jsonify({'error': 'User ID and task text are required'}), 400  # Ошибка, если данные отсутствуют

        user_id = data['user_id']
        task_text = data['task_text'].strip()  # Удаление пробелов из текста задачи
        
        if not task_text:
            return jsonify({'error': 'Task text cannot be empty'}), 400  # Ошибка, если текст пустой

        success = False
        for db_type in ['mariadb', 'sqlite']:
            conn = DatabaseConnection(db_type).connect()
            if not conn:
                print(f"Не удалось подключиться к {db_type}")
                continue
            try:
                cursor = conn.cursor()
                # Проверка существования пользователя
                cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
                result = cursor.fetchone()
                if not result:
                    print(f"{db_type}: Пользователь с id={user_id} не найден")
                    continue

                # Добавление новой задачи
                cursor.execute("INSERT INTO tasks (user_id, task_text) VALUES (?, ?)", (user_id, task_text))
                conn.commit()
                load_tasks_to_memory(user_id, conn, db_type)  # Обновление задач в памяти
                success = True
            except (mariadb.Error, sqlite3.Error) as e:
                print(f"Ошибка добавления задачи в {db_type}: {e}")
            finally:
                conn.close()
        
        if success:
            return jsonify({'message': 'Task added successfully', 'status': 'success'})  # Успешное добавление
        return jsonify({'error': 'Failed to add task to any database'}), 500  # Ошибка при добавлении

# Маршрут для обновления и удаления задач
@app.route('/api/tasks/<int:task_id>', methods=['PUT', 'DELETE'])
def modify_task(task_id):
    if request.method == 'PUT':
        data = request.get_json()  # Получение данных из PUT-запроса
        if not data or 'completed' not in data:
            return jsonify({'error': 'Completed status is required'}), 400  # Ошибка, если статус отсутствует

        success = False
        for db_type in ['mariadb', 'sqlite']:
            conn = DatabaseConnection(db_type).connect()
            if not conn:
                continue
            try:
                cursor = conn.cursor()
                # Проверка существования задачи
                cursor.execute("SELECT user_id FROM tasks WHERE id = ?", (task_id,))
                result = cursor.fetchone()
                if not result:
                    return jsonify({'error': 'Task not found'}), 404  # Ошибка, если задача не найдена
                
                user_id = result[0]
                # Обновление статуса задачи
                cursor.execute("UPDATE tasks SET completed = ? WHERE id = ?", (data['completed'], task_id))
                conn.commit()
                load_tasks_to_memory(user_id, conn, db_type)  # Обновление задач в памяти
                success = True
            except (mariadb.Error, sqlite3.Error) as e:
                print(f"Ошибка обновления задачи в {db_type}: {e}")
            finally:
                conn.close()
        
        if success:
            return jsonify({'message': 'Task updated', 'status': 'success'})  # Успешное обновление
        return jsonify({'error': 'Failed to update task in any database'}), 500  # Ошибка при обновлении

    elif request.method == 'DELETE':
        success = False
        for db_type in ['mariadb', 'sqlite']:
            conn = DatabaseConnection(db_type).connect()
            if not conn:
                continue
            try:
                cursor = conn.cursor()
                # Проверка существования задачи
                cursor.execute("SELECT user_id FROM tasks WHERE id = ?", (task_id,))
                result = cursor.fetchone()
                if not result:
                    return jsonify({'error': 'Task not found'}), 404  # Ошибка, если задача не найдена
                
                user_id = result[0]
                # Удаление задачи
                cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()
                load_tasks_to_memory(user_id, conn, db_type)  # Обновление задач в памяти
                success = True
            except (mariadb.Error, sqlite3.Error) as e:
                print(f"Ошибка удаления задачи в {db_type}: {e}")
            finally:
                conn.close()
        
        if success:
            return jsonify({'message': 'Task deleted', 'status': 'success'})  # Успешное удаление
        return jsonify({'error': 'Failed to delete task in any database'}), 500  # Ошибка при удалении

# Функция для загрузки задач в память
def load_tasks_to_memory(user_id: int, conn: object, db_type: str):
    cursor = conn.cursor()
    cursor.execute("SELECT id, task_text, completed FROM tasks WHERE user_id = ?", (user_id,))
    # Обновление списка задач в памяти для данного пользователя
    in_memory_tasks[user_id] = [{'id': t[0], 'text': t[1], 'completed': bool(t[2])} for t in cursor.fetchall()]

# Запуск приложения
if __name__ == '__main__':
    if init_databases():  # Инициализация баз данных перед запуском
        app.run()         # Запуск Flask-приложения
    else:
        sys.exit(1)       # Выход с ошибкой, если инициализация не удалась