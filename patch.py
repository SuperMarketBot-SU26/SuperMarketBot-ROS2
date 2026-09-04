import unicodedata

def remove_accents(s):
    if not isinstance(s, str):
        return s
    s = s.replace('Đ', 'D').replace('đ', 'd')
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
