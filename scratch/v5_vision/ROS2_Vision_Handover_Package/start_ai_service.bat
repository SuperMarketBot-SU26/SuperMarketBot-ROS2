@echo off
title SuperMarketBot YOLOv8 Shelf Vision & DroidCam Service
echo ================================================================
echo   SUPERMARKETBOT - REAL-TIME YOLOv8 SHELF VISION SERVICE
echo   PORT: 8000 | DASHBOARD: http://localhost:8000/vision/dashboard
echo ================================================================
cd /d "%~dp0"
python app.py
pause
