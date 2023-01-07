"""Setup script."""

import pathlib

from setuptools import setup


readme = (pathlib.Path(__file__).parent / 'README.md').read_text(encoding='utf-8')
install_requires = (pathlib.Path(__file__).parent / 'requirements.txt').read_text(encoding='utf-8').splitlines()

setup(
    name='wsgirouter3',
    version='0.8.4',
    description='WSGI routing library',
    long_description=readme,
    long_description_content_type='text/markdown',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Application',
    ],
    keywords='web services',
    author='Andrus Kütt',
    author_email='andrus.kuett@gmail.com',
    url='https://github.com/andruskutt/wsgirouter3',
    license='MIT',
    py_modules=['wsgirouter3'],
    python_requires='>=3.7',
    install_requires=install_requires,
)
