from pathlib import Path

from setuptools import find_packages, setup

package_name = 'avs_rescue_sim'


def package_data(directory):
    """Install a resource tree while preserving its relative directories."""
    entries = []
    root = Path(directory)
    if not root.exists():
        return entries
    for path in root.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            target = Path('share') / package_name / path.parent
            entries.append((str(target), [str(path)]))
    return entries

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ] + sum(
        (package_data(directory) for directory in
         ('launch', 'config', 'behavior_trees', 'worlds', 'models', 'urdf', 'rviz', 'maps')),
        [],
    ),
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='AVS Team',
    maintainer_email='contest@example.com',
    description='Autonomous rescue vehicle simulation for the AVS competition.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'vision_node = avs_rescue_sim.vision_node:main',
            'mission_node = avs_rescue_sim.mission_node:main',
            'camera_scan_node = avs_rescue_sim.camera_scan_node:main',
            'safety_node = avs_rescue_sim.safety_node:main',
            'navigation_map_node = avs_rescue_sim.navigation_map_node:main',
        ],
    },
)
