"""PyInstaller giriş betiği.

PyInstaller modül değil dosya istiyor (`-m ex30trips` kabul etmiyor). Mantık
pakette kalsın diye bu dosya yalnızca paketin giriş noktasını çağırıyor;
`py -3 main.py` ile doğrudan çalıştırmak da aynı sonucu veriyor.
"""

from ex30trips.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
