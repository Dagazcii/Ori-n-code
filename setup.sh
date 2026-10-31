#!/bin/bash

echo "=========================================="
echo "  Configurando entorno de Orion Code..."
echo "=========================================="

# 1. Actualizar repositorios y paquetes básicos de Termux
echo "[*] Actualizando paquetes..."
pkg update -y && pkg upgrade -y

# 2. Instalar herramientas esenciales (git, python, curl, build-tools, etc.)
echo "[*] Instalando herramientas esenciales (git, python, pip, etc.)..."
pkg install -y git python python-pip clang make libffi openssl

# 3. Actualizar pip
echo "[*] Actualizando pip..."
pip install --upgrade pip

# 4. Instalar librerías de Python comunes (si usas alguna en particular, ponla aquí)
# Ejemplo: pip install requests colorama
echo "[*] Instalando dependencias de Python..."
# pip install -r requirements.txt (Descomenta si creas un requirements.txt)

# 5. Configurar almacenamiento si no está configurado
if [ ! -d "$HOME/storage" ]; then
    echo "[*] Solicitando permisos de almacenamiento..."
    termux-setup-storage
fi

echo "=========================================="
echo "  ¡Instalación completada con éxito!"
echo "=========================================="
