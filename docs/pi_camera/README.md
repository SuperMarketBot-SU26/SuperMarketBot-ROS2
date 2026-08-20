# SuperMarketBot - Raspberry Pi AI Camera Integration Guide

This document outlines the feasibility, architecture, and team workflow for integrating the **Raspberry Pi AI Camera (Sony IMX500)** into the SuperMarketBot platform for Out-of-Stock and Face Detection tasks.

## 1. Hardware Feasibility (Highly Feasible & Plug-and-Play)
- **Physical Connection**: The Raspberry Pi 5 features two 22-pin MIPI CSI-2 transceivers. The AI Camera uses a standard ribbon cable that plugs directly into one of these ports and routes seamlessly through the cable slit on standard industrial Pi 5 cases.
- **Resource Efficiency**: The AI Camera is equipped with an onboard NPU (Sony IMX500). Neural network inference runs completely on the camera sensor. This offloads the computational burden from the Pi 5's CPU, preventing thermal throttling and ensuring that the robot's ROS 2 navigation stack remains unaffected.

## 2. Software Architecture (Standalone Systemd Service)
**Recommendation:** Run the camera integration as a standalone **Python Systemd Application**, rather than embedding it into ROS 2.

### Why Systemd over ROS 2?
- **Stability**: The camera's primary purpose is backend shelf analysis (detecting empty spaces and faces). Keeping this process isolated ensures that if the vision script crashes, it won't take down the robot's SLAM/AMCL navigation stack.
- **Bandwidth Efficiency**: Instead of transmitting heavy video streams over the supermarket's Wi-Fi, the system uses the `Picamera2` library to extract lightweight tensor metadata (bounding boxes) directly from the IMX500 chip.
- **Output**: The Python script formats this metadata into a clean JSON string (e.g., `{"shelf": 2, "empty_space": "30%", "missing_items": ["Product A"]}`) and publishes it to the backend via MQTT or HTTP.

## 3. Team Workflow & Division of Labor
To prevent bottlenecks, the integration is split into two distinct domains with a clear handoff point.

### Role A: Computer Vision / ML Engineer (Working on PC/GPU)
*Your teammate focuses entirely on model training and conversion.*
1. **Train Model**: Train a lightweight object detection model (e.g., **YOLOv8n** or **YOLO11n**) on supermarket shelf datasets.
2. **Quantization & Compilation (Crucial)**: The IMX500 cannot run standard PyTorch `.pt` files. The model must be quantized to INT8 using Sony's **Model Compression Toolkit (MCT)** and compiled using the **IMX500 Converter** on a powerful PC.
3. **The Handoff**: Deliver a zipped compilation folder (e.g., `packerOut.zip`) and a `labels.txt` file (mapping class IDs to product names) to the Hardware Engineer.

### Role B: Pi Integration Engineer (Working on Raspberry Pi)
*You focus on hardware integration, OS drivers, and backend communication.*
1. **OS Setup**: Mount the camera and install the required firmware by running `sudo apt install imx500-all`.
2. **Model Packaging**: Take the `packerOut.zip` from your teammate and run the packaging command on the Pi: 
   ```bash
   imx500-package -i packerOut.zip -o output_dir
   ```
   This generates the final **`.rpk`** file that the camera firmware requires.
3. **Data Pipeline**: Write the Python `Picamera2` script to load the `.rpk` file, parse the tensor outputs, format them as JSON, and transmit them.
4. **Pro-Tip (Parallel Development)**: *Do not wait for the custom YOLO model.* You can immediately build and test your entire Python JSON/MQTT pipeline using the official, pre-packaged **MobileNet SSD .rpk** model provided by Raspberry Pi. Once your teammate finishes the custom model, simply swap the `.rpk` file.
