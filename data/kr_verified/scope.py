import json,re,collections
K=json.load(open('/tmp/claude-0/krw/kr.json'))
BABY_BRAND={'그린핑거','아토팜','몽디에스','닥터아토','노엘로힐스','스킨베리어','궁중비책','보타니컬테라피','더블하트','퓨어루','케이맘','어네이브','디보트브리엘','베비언스','비더마틱','마이얼스데이','무스텔라','타가','페르바도','오가닉그라운드','차앤맘','아토앤오투','아이보들','소이베베','오가베베','프랭클린','아가애','앙또미뇽','스노우버디','베베숲'}
WORDS=r'키즈|베이비|아기|유아|어린이|영유아|아이|베베|엔젤키즈|썬키즈|레 앙팡|kids|baby|enfant'
out=[]
for k in K:
    name=k['제품명'] or ''; b=k['브랜드']
    w=re.findall(WORDS,name,re.I)
    if w: dec,why='include',f'product name says "{w[0]}"'
    elif re.search(r'해피 ?보',name) and b=='빌리프': dec,why='include','belif Happy Bo baby line (product page: "여린 아기 피부를 위한 순한 베이비 선블럭")'
    elif b in BABY_BRAND: dec,why='include',f'baby/kids-care brand ({b})'
    else: dec,why='exclude','no baby/kids wording in the product name and not a baby/kids-care brand'
    out.append({'ID':k['ID'],'brand':b,'name':name,'scope':dec,'scope_reason':why})
json.dump(out,open('/tmp/claude-0/krw/scope.json','w'),ensure_ascii=False,indent=0)
c=collections.Counter(o['scope'] for o in out);print(c)
for o in out:
    if o['scope']=='exclude': print(o['ID'][-3:],o['brand'],o['name'])
