from setuptools import setup

package_name = 'smb_nodes'

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
    description='Higher-level ROS2 nodes for SuperMarketBot (waypoint nav, state machine).',
    license='MIT',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'waypoint_follower = smb_nodes.waypoint_follower:main',
            'supervisor = smb_nodes.supervisor:main',
            'odom_imu_relay = smb_nodes.odom_imu_relay:main',
            'unified_relay = smb_nodes.unified_relay:main',
            'mapping_diagnostics = smb_nodes.mapping_diagnostics:main',
            'smb_mqtt_bridge = smb_nodes.smb_mqtt_bridge:main',
            'shelf_aggregator_node = smb_nodes.shelf_aggregator_node:main',
            'map_republisher = smb_nodes.map_republisher:main',
            'amcl_auto_corrector = smb_nodes.amcl_auto_corrector:main',
        ],
    },
)
