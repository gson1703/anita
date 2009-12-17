from distutils.core import setup
setup(name='anita',
      version='1.9',
      description='Automated NetBSD Installation and Test Application',
      author='Andreas Gustafsson',
      author_email='gson@gson.org',
      url='http://www.gson.org/netbsd/anita/',
      py_modules=['anita'],
      scripts=['anita'],
      data_files=[('man/man1', ['anita.1'])],
      )
