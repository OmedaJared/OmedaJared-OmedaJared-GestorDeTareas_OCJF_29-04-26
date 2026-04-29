import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import bcrypt # Para seguridad de contraseñas
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

app = Flask(__name__)
app.secret_key = "secreto_muy_seguro"
app.template_folder = 'CONTROL/templates'

# funciones para conectar a mongoDB Atlas usando variables de entorno
def get_db_connection():
    uri = os.getenv('MONGO_URI', '').strip()
    db_name = os.getenv('MONGO_DB', 'control_app_db').strip()

    if uri and not uri.startswith('mongodb+srv://tu_usuario'):  # Evitar URI con placeholders
        try:
            cliente = MongoClient(uri)
            cliente.admin.command('ping')
            print("✅ Conectado a MongoDB Atlas usando MONGO_URI")
            return cliente[db_name]
        except Exception as e:
            print(f"❌ Error conectando a MongoDB con MONGO_URI: {e}")

    usuario = os.getenv('MONGO_USER', '').strip()
    password = os.getenv('MONGO_PASSWORD', '').strip()
    cluster = os.getenv('MONGO_CLUSTER', '').strip()

    if all([usuario, password, cluster]):
        cluster = cluster.rstrip('.')
        if not cluster.endswith('.mongodb.net'):
            cluster = f"{cluster}.mongodb.net"

        uri = f"mongodb+srv://{usuario}:{password}@{cluster}/?retryWrites=true&w=majority"

        try:
            cliente = MongoClient(uri)
            cliente.admin.command('ping')
            print("✅ Conectado a MongoDB Atlas")
            return cliente[db_name]
        except Exception as e:
            print(f"❌ Error conectando a MongoDB Atlas: {e}")

    # Intentar conexión local si no hay Atlas
    try:
        cliente_local = MongoClient('mongodb://localhost:27017/')
        cliente_local.admin.command('ping')
        print("✅ Conectado a MongoDB local")
        return cliente_local[db_name]
    except Exception as e:
        print(f"❌ Error conectando a MongoDB local: {e}")
        print("⚠️ Usando modo offline (datos en memoria)")
        return None

db = get_db_connection()
usuarios_col = db['usuarios'] if db is not None else None
tareas_col = db['tareas'] if db is not None else None

# Modo offline para pruebas (si no hay DB, usa listas en memoria)
if db is None:
    print("⚠️ Modo offline activado: usando datos en memoria")
    usuarios_memoria = []
    tareas_memoria = []
else:
    usuarios_memoria = None
    tareas_memoria = None

# Crear índices para asegurar correos únicos
if usuarios_col is not None:
    usuarios_col.create_index("email", unique=True)

# --- RUTAS DE AUTENTICACIÓN ---

@app.route('/')
def inicio():
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # password por seguridad
        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        if usuarios_col is not None:
            try:
                usuarios_col.insert_one({
                    "nombre": nombre,
                    "email": email,
                    "password": hashed_pw,
                    "fecha_registro": datetime.now()
                })
                flash("Cuenta creada. ¡Inicia sesión!", "success")
                return redirect(url_for('inicio'))
            except:
                flash("El correo ya está registrado.", "error")
        else:
            # Modo offline: verificar si email ya existe
            if any(u['email'] == email for u in usuarios_memoria):
                flash("El correo ya está registrado.", "error")
            else:
                usuarios_memoria.append({
                    "_id": str(len(usuarios_memoria) + 1),
                    "nombre": nombre,
                    "email": email,
                    "password": hashed_pw,
                    "fecha_registro": datetime.now()
                })
                flash("Cuenta creada (modo offline). ¡Inicia sesión!", "success")
                return redirect(url_for('inicio'))
            
    return render_template('registro.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    
    if usuarios_col is not None:
        user = usuarios_col.find_one({"email": email})
    else:
        user = next((u for u in usuarios_memoria if u['email'] == email), None)
    
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
        session['user_id'] = str(user['_id'])
        session['user_name'] = user['nombre']
        return redirect(url_for('dashboard'))
    
    flash("Credenciales incorrectas", "error")
    return redirect(url_for('inicio'))

@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar():
    if request.method == 'POST':
        email = request.form.get('email')
        
        if usuarios_col is not None:
            user = usuarios_col.find_one({"email": email})
        else:
            user = next((u for u in usuarios_memoria if u['email'] == email), None)
            
        if user:
            flash("Se ha enviado un código a tu correo (Simulado)", "success")
        else:
            flash("Correo no encontrado", "error")
    return render_template('recuperar.html')

#  GESTOR DE TAREAS (CRUD) 

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('inicio'))
    
    # Obtener tareas del usuario logueado
    if tareas_col is not None:
        mis_tareas = list(tareas_col.find({"usuario_id": session['user_id']}))
    else:
        mis_tareas = [t for t in tareas_memoria if t['usuario_id'] == session['user_id']]
        
    return render_template('dashboard.html', tareas=mis_tareas)

@app.route('/nueva_tarea', methods=['POST'])
def nueva_tarea():
    if 'user_id' in session:
        titulo = request.form.get('titulo')
        if tareas_col is not None:
            tareas_col.insert_one({
                "usuario_id": session['user_id'],
                "titulo": titulo,
                "estado": "pendiente",
                "fecha": datetime.now()
            })
        else:
            tareas_memoria.append({
                "_id": str(len(tareas_memoria) + 1),
                "usuario_id": session['user_id'],
                "titulo": titulo,
                "estado": "pendiente",
                "fecha": datetime.now()
            })
    return redirect(url_for('dashboard'))

@app.route('/completar_tarea/<tarea_id>', methods=['POST'])
def completar_tarea(tarea_id):
    if 'user_id' in session:
        if tareas_col is not None:
            from bson.objectid import ObjectId
            tareas_col.update_one(
                {"_id": ObjectId(tarea_id), "usuario_id": session['user_id']},
                {"$set": {"estado": "completada"}}
            )
        else:
            for t in tareas_memoria:
                if t['_id'] == tarea_id and t['usuario_id'] == session['user_id']:
                    t['estado'] = 'completada'
                    break
    return redirect(url_for('dashboard'))

@app.route('/eliminar_tarea/<tarea_id>', methods=['POST'])
def eliminar_tarea(tarea_id):
    if 'user_id' in session:
        if tareas_col is not None:
            from bson.objectid import ObjectId
            tareas_col.delete_one(
                {"_id": ObjectId(tarea_id), "usuario_id": session['user_id']}
            )
        else:
            tareas_memoria[:] = [t for t in tareas_memoria if not (t['_id'] == tarea_id and t['usuario_id'] == session['user_id'])]
    return redirect(url_for('dashboard'))

@app.route('/editar_tarea/<tarea_id>', methods=['GET', 'POST'])
def editar_tarea(tarea_id):
    if 'user_id' not in session: return redirect(url_for('inicio'))
    
    # Buscar tarea
    if tareas_col is not None:
        from bson.objectid import ObjectId
        tarea = tareas_col.find_one({"_id": ObjectId(tarea_id), "usuario_id": session['user_id']})
    else:
        tarea = next((t for t in tareas_memoria if t['_id'] == tarea_id and t['usuario_id'] == session['user_id']), None)
        
    if not tarea:
        flash("Tarea no encontrada.", "error")
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        nuevo_titulo = request.form.get('titulo')
        if tareas_col is not None:
            tareas_col.update_one(
                {"_id": ObjectId(tarea_id), "usuario_id": session['user_id']},
                {"$set": {"titulo": nuevo_titulo}}
            )
        else:
            tarea['titulo'] = nuevo_titulo
        return redirect(url_for('dashboard'))
    
    return render_template('editar_tarea.html', tarea=tarea)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))

if __name__ == '__main__':
    app.run(debug=True)
