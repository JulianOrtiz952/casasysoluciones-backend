# Guía de Configuración y Ejecución Local

Esta guía detalla los pasos necesarios para levantar el proyecto **Casas y Soluciones** (tanto frontend como backend) en tu entorno de desarrollo local.

---

## 1. Backend (Django / Python)

El backend de la aplicación se encuentra en la carpeta `backend/`. Sigue estos pasos para configurarlo:

### Paso 1: Crear y activar el entorno virtual
Desde la raíz del proyecto, ingresa a la carpeta `backend/` y crea el entorno virtual:
```bash
cd backend
python -m venv venv
```
Activa el entorno virtual según tu shell:
* **Bash/Zsh**: `source venv/bin/activate`
* **Fish**: `source venv/bin/activate.fish`
* **Windows (Command Prompt)**: `venv\Scripts\activate.bat`
* **Windows (PowerShell)**: `venv\Scripts\Activate.ps1`

### Paso 2: Instalar las dependencias
Con el entorno virtual activo, instala todos los paquetes necesarios:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Paso 3: Configurar variables de entorno
Crea tu archivo `.env` en la raíz de la carpeta `backend/` copiando el archivo de ejemplo:
```bash
cp .env.example .env
```
Ajusta los valores del archivo `.env` para desarrollo local si lo requieres. Por defecto viene con:
```env
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:3000
CSRF_TRUSTED_ORIGINS=http://localhost:3000
DATABASE_URL=
```
*(Nota: Si dejas `DATABASE_URL` en blanco, el backend automáticamente usará una base de datos local SQLite en la carpeta `data/db.sqlite3`)*.

### Paso 4: Ejecutar migraciones
Crea las tablas correspondientes en tu base de datos local ejecutando:
```bash
python manage.py migrate
```

### Paso 5: Crear un usuario administrador (opcional)
Si deseas acceder al panel administrativo de Django o de la web con todos los permisos:
```bash
python manage.py createsuperuser
```

### Paso 6: Correr el servidor local
Levanta el servidor de desarrollo local:
```bash
python manage.py runserver
```
El backend quedará disponible en: **http://localhost:8000**

---

## 2. Frontend (Next.js / Node)

El frontend de la aplicación se encuentra en la carpeta `frontend/`. Sigue estos pasos para configurarlo:

### Paso 1: Instalar dependencias
Ingresa a la carpeta `frontend/` e instala las dependencias de Node:
```bash
cd ../frontend
npm install
```

### Paso 2: Configurar variables de entorno
Crea tu archivo `.env.local` en la raíz de la carpeta `frontend/` copiando el archivo de ejemplo:
```bash
cp .env.local.example .env.local
```
El archivo `.env.local` debe tener la URL apuntando a tu backend local:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Paso 3: Correr el servidor local
Inicia el servidor de desarrollo de Next.js:
```bash
npm run dev
```
El frontend quedará disponible en: **http://localhost:3000**
