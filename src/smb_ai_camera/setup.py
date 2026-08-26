from setuptools import setup

package_name = 'smb_ai_camera'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
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
            'shelf_patrol_capture = smb_ai_camera.shelf_patrol_capture:main',
        ],
    },
)
