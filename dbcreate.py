import mysql.connector
from mysql.connector import errorcode
import sys

# Database configuration
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "acore"
DB_PASSWORD = "acore"
DB_NAME = "expense_tracker"

def create_database():
    """Create the database if it doesn't exist"""
    conn = None
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cursor = conn.cursor(dictionary=True)
        
        # Try to create database if it doesn't exist
        try:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"Database {DB_NAME} created successfully or already exists.")
        except mysql.connector.Error as err:
            print(f"Failed to create database: {err}")
            sys.exit(1)
            
        # Switch to the database
        cursor.execute(f"USE {DB_NAME}")
        
        # Create tables
        create_tables(cursor)
        
        conn.commit()
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        sys.exit(1)
    finally:
        if conn:
            cursor.close()
            conn.close()

def create_tables(cursor):
    """Create all necessary tables"""
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password VARCHAR(255) NOT NULL,
        email VARCHAR(100) NOT NULL UNIQUE,
        full_name VARCHAR(100) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB
    """)
    
    # Currency exchange rates table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cot_moed_ext (
        id INT AUTO_INCREMENT PRIMARY KEY,
        currency VARCHAR(50) NOT NULL,
        buy_rate DECIMAL(10, 4) NOT NULL,
        sell_rate DECIMAL(10, 4) NOT NULL,
        date DATE NOT NULL,
        time_info VARCHAR(50) NOT NULL,
        rate_type VARCHAR(20) DEFAULT 'Regular',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY currency_date_time_type (currency, date, time_info, rate_type)
    ) ENGINE=InnoDB
    """)
    
    # Expense categories table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expense_categories (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        name VARCHAR(50) NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY (user_id, name),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """)
    
    # Expenses table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        category_id INT NOT NULL,
        amount DECIMAL(10, 2) NOT NULL,
        description TEXT,
        date DATE NOT NULL,
        is_recurring BOOLEAN DEFAULT FALSE,
        is_installment BOOLEAN DEFAULT FALSE,
        parent_expense_id INT NULL,
        recurring_type ENUM('monthly', 'yearly', 'weekly') NULL,
        recurring_end_date DATE NULL,
        installment_number INT NULL,
        total_installments INT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (category_id) REFERENCES expense_categories(id) ON DELETE RESTRICT,
        FOREIGN KEY (parent_expense_id) REFERENCES expenses(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """)
    
    # Investment types table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS investment_types (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        name VARCHAR(50) NOT NULL,
        description TEXT,
        risk_level ENUM('Low', 'Medium', 'High') NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY (user_id, name),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """)
    
    # Investments table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS investments (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        type_id INT NOT NULL,
        amount DECIMAL(10, 2) NOT NULL,
        description TEXT,
        date DATE NOT NULL,
        expected_return DECIMAL(5, 2),
        maturity_date DATE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (type_id) REFERENCES investment_types(id) ON DELETE RESTRICT
    ) ENGINE=InnoDB
    """)
    
    # Income sources table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS income_sources (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        name VARCHAR(50) NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY (user_id, name),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """)
    
    # Income table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS income (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        source_id INT NOT NULL,
        amount DECIMAL(10, 2) NOT NULL,
        description TEXT,
        date DATE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (source_id) REFERENCES income_sources(id) ON DELETE RESTRICT
    ) ENGINE=InnoDB
    """)
    
    # Budgets table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS budgets (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        category_id INT NOT NULL,
        amount DECIMAL(10, 2) NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (category_id) REFERENCES expense_categories(id) ON DELETE RESTRICT,
        UNIQUE KEY (user_id, category_id, start_date, end_date)
    ) ENGINE=InnoDB
    """)
    
    # Insert default data
    insert_default_data(cursor)
    
    print("All tables created successfully.")

def insert_default_data(cursor):
    """Insert default data into tables"""
    
    # Check if expense categories exist
    cursor.execute("SELECT COUNT(*) as count FROM expense_categories WHERE user_id IS NULL")
    result = cursor.fetchone()
    if result['count'] == 0:
        # Insert default expense categories (global/system defaults with NULL user_id)
        expense_categories = [
            (None, 'Alimentação', 'Gastos com comida e restaurantes'),
            (None, 'Moradia', 'Aluguel, condomínio, IPTU, etc'),
            (None, 'Transporte', 'Combustível, transporte público, manutenção'),
            (None, 'Saúde', 'Plano de saúde, medicamentos, consultas'),
            (None, 'Educação', 'Mensalidades, cursos, livros'),
            (None, 'Lazer', 'Entretenimento, viagens, hobbies'),
            (None, 'Vestuário', 'Roupas e acessórios'),
            (None, 'Serviços', 'Internet, telefone, streaming'),
            (None, 'Outros', 'Gastos diversos')
        ]
        cursor.executemany(
            "INSERT INTO expense_categories (user_id, name, description) VALUES (%s, %s, %s)",
            expense_categories
        )
    
    # Check if investment types exist
    cursor.execute("SELECT COUNT(*) as count FROM investment_types WHERE user_id IS NULL")
    result = cursor.fetchone()
    if result['count'] == 0:
        # Insert default investment types (global/system defaults with NULL user_id)
        investment_types = [
            (None, 'Poupança', 'Conta poupança tradicional', 'Low'),
            (None, 'CDB', 'Certificado de Depósito Bancário', 'Low'),
            (None, 'Tesouro Direto', 'Títulos públicos federais', 'Low'),
            (None, 'Fundos de Renda Fixa', 'Fundos que investem em títulos de renda fixa', 'Low'),
            (None, 'Fundos Imobiliários', 'Fundos que investem em imóveis', 'Medium'),
            (None, 'Ações', 'Ações de empresas listadas na bolsa', 'High'),
            (None, 'Fundos de Ações', 'Fundos que investem em ações', 'High'),
            (None, 'Criptomoedas', 'Bitcoin e outras criptomoedas', 'High')
        ]
        cursor.executemany(
            "INSERT INTO investment_types (user_id, name, description, risk_level) VALUES (%s, %s, %s, %s)",
            investment_types
        )
    
    # Check if income sources exist
    cursor.execute("SELECT COUNT(*) as count FROM income_sources WHERE user_id IS NULL")
    result = cursor.fetchone()
    if result['count'] == 0:
        # Insert default income sources (global/system defaults with NULL user_id)
        income_sources = [
            (None, 'Salário', 'Remuneração mensal do trabalho'),
            (None, 'Freelance', 'Trabalhos pontuais'),
            (None, 'Investimentos', 'Rendimentos de investimentos'),
            (None, 'Aluguel', 'Rendimentos de aluguel de imóveis'),
            (None, 'Outros', 'Outras fontes de renda')
        ]
        cursor.executemany(
            "INSERT INTO income_sources (user_id, name, description) VALUES (%s, %s, %s)",
            income_sources
        )

if __name__ == "__main__":
    create_database()
    print("Database setup completed successfully.")
