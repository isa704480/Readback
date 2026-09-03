import random, statistics
random.seed(7)
D='0123456789'; L='ABCDEFGHIJKLMNOPQRSTUVWXYZ'

# ---------- ISO 6346 ----------
ISO_LET={}
v=10
for ch in L:
    while v%11==0: v+=1
    ISO_LET[ch]=v; v+=1
def iso_val(c):
    if c.isdigit(): return int(c)
    return ISO_LET[c]
def iso_cd(s10):
    t=sum(iso_val(c)*(2**i) for i,c in enumerate(s10))
    return t%11%10
def iso_ok(s):
    return len(s)==11 and s[:4].isalpha() and s[3] in 'UJZ' and s[4:].isdigit() and iso_cd(s[:10])==int(s[10])

# ---------- VIN ----------
VT={**{c:i+1 for i,c in enumerate('ABCDEFGH')},**{'J':1,'K':2,'L':3,'M':4,'N':5,'P':7,'R':9},
    **{'S':2,'T':3,'U':4,'V':5,'W':6,'X':7,'Y':8,'Z':9}}
VW=[8,7,6,5,4,3,2,10,0,9,8,7,6,5,4,3,2]
VIN_ALPHA=D+''.join(c for c in L if c not in 'IOQ')
def vin_ok(s):
    if len(s)!=17 or any(c not in VIN_ALPHA for c in s): return False
    t=sum((int(c) if c.isdigit() else VT[c])*VW[i] for i,c in enumerate(s))
    r=t%11
    return s[8]==('X' if r==10 else str(r))

# ---------- NHS ----------
def nhs_ok(s):
    if len(s)!=10 or not s.isdigit(): return False
    t=sum(int(s[i])*(10-i) for i in range(9))
    c=11-(t%11)
    if c==11: c=0
    if c==10: return False
    return c==int(s[9])

# ---------- Luhn / IMEI ----------
def luhn_ok(s):
    if not s.isdigit(): return False
    t=0
    for i,c in enumerate(reversed(s)):
        d=int(c)
        if i%2==1:
            d*=2
            if d>9: d-=9
        t+=d
    return t%10==0

# ---------- EAN13 ----------
def ean_ok(s):
    if len(s)!=13 or not s.isdigit(): return False
    t=sum(int(c)*(1 if i%2==0 else 3) for i,c in enumerate(s[:12]))
    return (10-t%10)%10==int(s[12])

# ---------- ISBN10 ----------
def isbn10_ok(s):
    if len(s)!=10: return False
    t=0
    for i,c in enumerate(s):
        if c=='X':
            if i!=9: return False
            d=10
        elif c.isdigit(): d=int(c)
        else: return False
        t+=d*(10-i)
    return t%11==0

# ---------- IBAN ----------
IBAN_LEN={'GB':22,'DE':22,'FR':27,'NL':18,'ES':24,'IT':27,'CH':21,'BE':16,'AT':20,'PL':28}
def iban_ok(s):
    s=s.replace(' ','')
    cc=s[:2]
    if cc in IBAN_LEN and len(s)!=IBAN_LEN[cc]: return False
    r=s[4:]+s[:4]
    n=''.join(str(ord(c)-55) if c.isalpha() else c for c in r)
    if not n.isdigit(): return False
    return int(n)%97==1

# ---------- SEDOL ----------
SW=[1,3,1,7,3,9,1]
SED_ALPHA=D+'BCDFGHJKLMNPQRSTVWXYZ'  # consonants only, no vowels
def sed_ok(s):
    if len(s)!=7 or any(c not in SED_ALPHA for c in s): return False
    t=sum((int(c) if c.isdigit() else ord(c)-55)*SW[i] for i,c in enumerate(s))
    return t%10==0

# ---------- ISIN ----------
def isin_ok(s):
    if len(s)!=12: return False
    n=''.join(str(ord(c)-55) if c.isalpha() else c for c in s[:11])
    if not n.isdigit(): return False
    t=0
    for i,c in enumerate(reversed(n)):
        d=int(c)
        if i%2==0:
            d*=2
            if d>9: d-=9
        t+=d
    return (10-t%10)%10==int(s[11])

# ---------- CPF ----------
def cpf_ok(s):
    if len(s)!=11 or not s.isdigit(): return False
    for k in (9,10):
        t=sum(int(s[i])*(k+1-i) for i in range(k))
        d=(11-t%11); d=0 if d>=10 else d
        if d!=int(s[k]): return False
    return True

if __name__ == '__main__':
    print("=== SANITY CHECKS (known-good values) ===")
    tests=[
     ("ISO6346 CSQU3054383", iso_ok("CSQU3054383"), True),
     ("ISO6346 MSCU1234565", iso_ok("MSCU1234565"), None),
     ("ISO6346 bad CSQU3054384", iso_ok("CSQU3054384"), False),
     ("VIN 1HGCM82633A004352", vin_ok("1HGCM82633A004352"), True),
     ("VIN 11111111111111111", vin_ok("11111111111111111"), True),
     ("VIN WBA3A5C55DF123456 (rand)", vin_ok("WBA3A5C55DF123456"), None),
     ("NHS 9434765919", nhs_ok("9434765919"), True),
     ("NHS 9434765918 bad", nhs_ok("9434765918"), False),
     ("Luhn 79927398713", luhn_ok("79927398713"), True),
     ("NPI 1234567893 (80840+)", luhn_ok("80840"+"1234567893"), True),
     ("EAN 4006381333931", ean_ok("4006381333931"), True),
     ("ISBN10 0306406152", isbn10_ok("0306406152"), True),
     ("ISBN10 043942089X", isbn10_ok("043942089X"), True),
     ("IBAN GB82WEST12345698765432", iban_ok("GB82WEST12345698765432"), True),
     ("IBAN DE89370400440532013000", iban_ok("DE89370400440532013000"), True),
     ("SEDOL 0263494", sed_ok("0263494"), True),
     ("SEDOL 5852842", sed_ok("5852842"), True),
     ("ISIN US0378331005 (Apple)", isin_ok("US0378331005"), True),
     ("ISIN GB0002634946 (BAE)", isin_ok("GB0002634946"), True),
     ("ISIN AU0000XVGZA3", isin_ok("AU0000XVGZA3"), True),
    ]
    for name,got,exp in tests:
        mark = "  " if exp is None else ("OK " if got==exp else "!! ")
        print(f"{mark}{name:42s} -> {got}")
