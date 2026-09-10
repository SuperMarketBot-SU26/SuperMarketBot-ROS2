import os
from setuptools import setup

package_name = 'smb_ai_camera'

def get_data_files():
    data_files = [
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ]
    
    # Recursively add files from resource directories
    for root, dirs, files in os.walk('resource/models'):
        if files:
            install_root = root.replace('resource/', '', 1)
            install_path = os.path.join('share', package_name, install_root)
            data_files.append((install_path, [os.path.join(root, f) for f in files]))
            
    for root, dirs, files in os.walk('resource/reference_products'):
        if files:
            install_root = root.replace('resource/', '', 1)
            install_path = os.path.join('share', package_name, install_root)
            data_files.append((install_path, [os.path.join(root, f) for f in files]))
            
    for root, dirs, files in os.walk('resource/aruco_tags'):
        if files:
            install_root = root.replace('resource/', '', 1)
            install_path = os.path.join('share', package_name, install_root)
            data_files.append((install_path, [os.path.join(root, f) for f in files]))
            
    return data_files

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=get_data_files(),
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Khoa Tran',
    maintainer_email='khoatnnse183385@fpt.edu.vn',
    description='Pi Camera and Shelf Patrol OOS Vision Pipeline for SuperMarketBot.',
    license='MIT',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'pi_camera_node = smb_ai_camera.pi_camera_node:main',
            'shelf_vision_node = smb_ai_camera.shelf_vision_node:main',
            'shelf_sweep_telemetry_node = smb_ai_camera.shelf_sweep_telemetry_node:main',
        ],
    },
)
