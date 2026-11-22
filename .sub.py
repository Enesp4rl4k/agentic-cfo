def sub(p, pairs):
    s=open(p,encoding='utf8',newline='').read()
    crlf='\r\n' in s
    s=s.replace('\r\n','\n')
    for old,new in pairs:
        assert old in s,(p,old[:60])
        s=s.replace(old,new,1)
    if crlf: s=s.replace('\n','\r\n')
    open(p,'w',encoding='utf8',newline='').write(s)
