#!/bin/bash

echo "=========================================="
echo "  Configurando entorno completo de Orion..."
echo "=========================================="

# 1. Actualizar repositorios y paquetes básicos de Termux
echo "[*] Actualizando paquetes..."
pkg update -y && pkg upgrade -y

# 2. Instalar herramientas esenciales
echo "[*] Instalando git, python, pip y utilidades..."
pkg install -y git python python-pip clang make libffi openssl

# 3. Actualizar pip
echo "[*] Actualizando pip..."
pip install --upgrade pip

# 4. Instalar dependencias de Python si existen
if [ -f "requirements.txt" ]; then
    echo "[*] Instalando dependencias desde requirements.txt..."
    pip install -r requirements.txt
fi

# 5. Configurar almacenamiento (opcional/interactivo)
if [ ! -d "$HOME/storage" ]; then
    echo "[*] Solicitando permisos de almacenamiento..."
    termux-setup-storage
fi

# 6. Crear el comando directo 'orion' en el sistema
echo "[*] Configurando el comando global 'orion'..."

# Directorio de binarios de termux
BIN_DIR="/data/data/com.termux/files/usr/bin"
REPO_DIR="$(pwd)"

# Detectar el script principal (busca orion.py, main.py o similar en el repo)
MAIN_SCRIPT=""
if [ -f "orion.py" ]; then
    MAIN_SCRIPT="orion.py"
elif [ -f "main.py" ]; then
    MAIN_SCRIPT="main.py"
else
    MAIN_SCRIPT="orion.py" # Por defecto
fi

# Crear el script ejecutable en /usr/bin/orion
cat << EOF > "$BIN_DIR/orion"
#!/bin/bash
cd "$REPO_DIR"
python "$MAIN_SCRIPT" "\$@"
EOF

chmod +x "$BIN_DIR/orion"

echo "=================================================="
echo "  ¡Instalación y configuración completas!"
echo "  Ahora solo escribe: orion"
echo "=================================================="
