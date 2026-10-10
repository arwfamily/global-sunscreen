import json,re,sys,io,contextlib,collections
sys.path.insert(0,'/tmp/claude-0/krw/scripts')
with contextlib.redirect_stdout(io.StringIO()):
    from uv import items,N,KR_UV,OTHER_UVA,EXTRA_ALIASES,MIN,find
K={k['ID']:k for k in json.load(open('/tmp/claude-0/krw/kr.json'))}
S={s['ID']:s for s in json.load(open('/tmp/claude-0/krw/scope.json'))}
TC=json.load(open('/tmp/claude-0/krw/textcheck.json'))
def P(n): return [k for k in K if k.endswith(n)][0]
FIX={  # corrected lists (verified against label images / page text)
 P('011'):"정제수, 징크옥사이드, 다이카프릴릴카보네이트, 해바라기씨오일, 비즈왁스, 운데케인, 글리세린, 카프릴릭/카프릭트라이글리세라이드, 다이카프릴릴에터, 소듐클로라이드, 트라이데케인, 폴리글리세릴-2다이폴리하이드록시스테아레이트, 폴리글리세릴-3다이아이소스테아레이트, 소듐레불리네이트, 글리세릴카프릴레이트, 폴리글리세릴-4다이아이소스테아레이트/폴리하이드록시스테아레이트/세바케이트, 소듐아니세이트, 폴리글리세릴-3올리에이트, 베타인, 하이드로제네이티드레시틴, 다이아이소스테아로일폴리글리세릴-3다이머다이리놀리에이트, 프로판다이올, 칼라민(100ppm), 토코페롤, 병풀추출물, 1,2-헥산다이올, 옥틸도데칸올, 딜추출물, 패션프룻열매추출물, 로켓잎추출물, 세라마이드엔피, 잔탄검, 산소(0.001ppm)",
 P('018'):"정제수, 사이클로펜타실록세인, 징크옥사이드, 티타늄디옥사이드, 피이지-10다이메티콘, 부틸렌글라이콜다이카프릴레이트/다이카프레이트, 카프릴릴메티콘, 글리세린, 사이클로헥사실록세인, 다이프로필렌글라이콜, 판테놀, 헥실라우레이트, 1,2-헥산다이올, 마그네슘설페이트, 카프릴릭/카프릭트라이글리세라이드, 다이스테아다이모늄헥토라이트, 하이드로젠다이메티콘, 부틸렌글라이콜, 다이메티콘크로스폴리머, 알루미나, 트라이에톡시카프릴릴실레인, 아이소스테아릭애씨드, 폴리글리세릴-2다이폴리하이드록시스테아레이트, 징크스테아레이트, 다이스테아릴다이모늄클로라이드, 토코페릴아세테이트, 육두구추출물, 메도우스위트추출물, 귀리커넬추출물*+, 별꽃추출물*+, 마트리카리아꽃추출물*, 다마스크장미꽃추출물*, 삼색제비꽃추출물*, 포트마리골드꽃추출물+, 개박하추출물+, 라즈베리잎추출물+, 와일드인디고뿌리추출물+, 오렌지껍질오일**, 라임전초오일**, 센티드제라늄꽃오일**, 로즈마리잎오일**, 리모넨, 시트로넬올, 제라니올, 시트랄, 리날룰",
 P('133'):"부틸렌글라이콜다이카프릴레이트/다이카프레이트, C12-15알킬벤조에이트, 징크옥사이드, 티타늄디옥사이드, 세레신, 트라이에틸헥사노인, 합성왁스, 피토스테릴/이소스테아릴/세틸/스테아릴/베헤닐다이머디리놀리에이트, 폴리하이드록시스테아릭애씨드, 에틸렌/프로필렌코폴리머, 알루미늄스테아레이트, 다이아이소스테아릴말레이트, 알루미나, 1,2-헥산다이올, 다이메티콘, 트라이에톡시카프릴릴실레인, 쿼터늄-18벤토나이트, 토코페릴아세테이트, 칼라민, 합성플루오르플로고파이트, 향료",
}
k=K[P('017')]; FIX[P('017')]=k['전성분'].replace('개박하추출물*+','개박하추출물*')
k=K[P('004')]; FIX[P('004')]=k['전성분'].replace('징크옥사이드, 000ppm)','징크옥사이드(192,000ppm)')
k=K[P('153')]; FIX[P('153')]=k['전성분'].replace('2, 3-부탄다이올','2,3-부탄다이올')
k=K[P('132')]; FIX[P('132')]=re.sub(r'향료\s*\*분사제.*$','향료',k['전성분'],flags=re.S)
NOTE={P('011'):'Corrected from the label image (read twice): MUSE had two extra items, one wrong item (올리베이트 vs 올리에이트) and an order error.',
 P('018'):'Corrected from the label image (read twice): 하이드로젠다이메티콘, not 하이드로제네이티드폴리데센 (taken from a sibling product); three spelling fixes.',
 P('133'):'Replaced: MUSE list came from a scraped ingredient-dictionary text that does not match the label image; label image list used (read twice).',
 P('017'):'Marker fixed: 개박하추출물* (image), MUSE had *+.',
 P('004'):'Split error fixed: 징크옥사이드(192,000ppm) — MUSE split it at the thousands comma.',
 P('153'):'Formatting fixed: 2,3-부탄다이올.',
 P('132'):'Cleaned: the footnote "*분사제: 디메칠에텔(DME)" (propellant) is not an ingredient item.',
 P('145'):'Ingredient list from a marketing graphic, not the 상품고시 table. The page shows SPF44 PA++++, not SPF50+.',
 P('160'):'Items verified, but the image groups ingredients by EWG grade, so the printed label ORDER could not be verified. Volume on 상품고시: 13ml.',
 P('162'):'Items verified from an EWG-grade card; label order not confirmable from the images.',
 P('179'):'Header on the image is generic ("페르바도 어린이 선크림 전성분"); SKU not named on the image.',
 P('139'):'Verified against the regular-edition 21g list (brand mall + Kurly); the cited limited-edition page did not load.',
 P('175'):'Verified against the regular-edition brand-mall list (product 3116); the cited page did not load.',
 P('154'):'Spec table shows two sibling products; the 야외놀이 선크림 block was used.',}
STATUS={}
for i in ['003','004','005','006','007','008','111','112','113','114','115','130','131','137','138','140','132']: STATUS[P(i)]=('verified','official brand/retailer page text (fetched 2026-10-09) matched item by item')
for i in ['139','175']: STATUS[P(i)]=('verified','official brand/retailer page text matched (regular edition)')
for i in ['125','126']: STATUS[P(i)]=('verified','SSG 상품필수정보 text matched item by item')
for i in ['009','015','118','143','144','153','154','179','145','017','162','160']: STATUS[P(i)]=('verified','label image on the official page; two independent readings agree')
for i in ['011','018','133']: STATUS[P(i)]=('verified (corrected)','label image on the official page; corrected list confirmed by a second and third reading')

FIX[P('076')]=K[P('076')]['전성분'].replace('사이클로헥사시릴록세인','사이클로헥사실록세인')
FIX[P('077')]="부틸렌글라이콜다이카프릴레이트/다이카프레이트, 아이소프로필팔미테이트, 합성왁스, 징크옥사이드, C12-15알킬벤조에이트, 폴리메틸실세스퀴옥세인, 벤조트라이아졸릴도데실p-크레솔, 비닐다이메티콘/메티콘실세스퀴옥세인크로스폴리머, 카프릴릭/카프릭트라이글리세라이드, 에이치디아이/트라이메틸올헥실락톤크로스폴리머, 부틸옥틸살리실레이트, 비닐다이메티콘, 아크릴레이트코폴리머, 오조케라이트, 산소(0.01ppm), 세라마이드엔피, 엑토인, 다시마추출물, 당느릅나무뿌리추출물, 들깨잎추출물, 서양민들레뿌리줄기/뿌리추출물, 신선초잎/줄기추출물, 알로에베라잎추출물, 약모밀추출물, 제비꽃꽃추출물, 참마뿌리추출물, 타임잎추출물, 포트마리골드꽃추출물, 하이드로제네이티드레시틴, 폴리글리세릴-4다이아이소스테아레이트/폴리하이드록시스테아레이트/세바케이트, 트라이에톡시카프릴릴실레인, 폴리하이드록시스테아릭애씨드, 글리세릴카프릴레이트, 카프릴릴글라이콜, 실리카, 다이프로필렌글라이콜, 에틸헥실글리세린, 정제수, 글라이코리피드, 소듐서팩틴, 토코페롤, 글리세린, 1,2-헥산다이올"
FIX[P('116')]="징크옥사이드, 옥틸도데칸올, 아이소프로필팔미테이트, 다이아이소프로필세바케이트, 코코-카프릴레이트/카프레이트, 비닐다이메티콘/메티콘실세스퀴옥세인크로스폴리머, 비닐다이메티콘, 다이부틸에틸헥사노일글루타마이드, 다이부틸라우로일글루타마이드, 폴리글리세릴-6폴리리시놀리에이트, 실리카실릴레이트, 에이치디아이/트라이메틸올헥실락톤크로스폴리머, 폴리하이드록시스테아릭애씨드, 벤조트라이아졸릴도데실P-크레솔, 판테놀, 세라마이드엔피, 마트리카리아꽃추출물, 폴스애플민트잎추출물, 녹차추출물, 타임잎추출물, 글리세린, 부틸렌글라이콜, 글리세릴카프릴레이트, 트라이하이드록시스테아린, 정제수, 트라이에톡시카프릴릴실레인, 실리카, 1,2-헥산다이올, 에틸헥실글리세린"
FIX[P('120')]="편백수(38%), 징크옥사이드, 카프릴릴메티콘, 다이아이소프로필세바케이트, 부틸옥틸살리실레이트, 부틸렌글라이콜다이카프릴레이트/다이카프레이트, 부틸렌글라이콜, 티타늄디옥사이드, 라우릴폴리글리세릴-3폴리다이메틸실록시에틸다이메티콘, 나이아신아마이드, 1,2-헥산다이올, 정제수, 칼라민, 폴리글리세릴-4다이아이소스테아레이트/폴리하이드록시스테아레이트/세바케이트, 메틸메타크릴레이트크로스폴리머, 에칠헥실트리아존, 다이에틸헥실2,6-나프탈레이트, 디에칠아미노하이드록시벤조일헥실벤조에이트, 비스-에칠헥실옥시페놀메톡시페닐트리아진, 마그네슘설페이트, 트라이에톡시카프릴릴실레인, 다이스테아다이모늄헥토라이트, 폴리글리세릴-3폴리다이메틸실록시에틸다이메티콘, 판테놀, 동백나무꽃추출물, 잣나무씨추출물, 소나무잎추출물, 브이피/에이코신코폴리머, 폴리메틸실세스퀴옥세인, 코코-카프릴레이트/카프레이트, 폴리하이드록시스테아릭애씨드, 콜라겐, 락토바실러스발효용해물, 류코노스톡/무발효여과물, 에틸헥실글리세린, 글리세릴카프릴레이트, 카프릴릴글라이콜, 펜틸렌글라이콜, 메틸다이아이소프로필프로피온아마이드, 알루미늄하이드록사이드, 잔탄검, 아데노신, 사이아노코발아민, 3-O-에틸아스코빅애씨드, 토코페롤, 향료"
FIX[P('173')]="트라이에틸헥사노인, 다이메티콘, 실리카, 에칠헥실메톡시신나메이트, 페닐트라이메티콘, 비닐다이메티콘/메티콘실세스퀴옥세인크로스폴리머, 마이카(CI 77019), 에칠헥실살리실레이트, 폴리에틸렌, 파라핀, 디에칠아미노하이드록시벤조일헥실벤조에이트, 비스-에칠헥실옥시페놀메톡시페닐트리아진, 옥토크릴렌, 솔비탄아이소스테아레이트, 하이드롤라이즈드식물성단백질, 자일리틸글루코사이드, 자일리톨, 마이크로크리스탈린왁스, 트라이에톡시카프릴릴실레인, 알루미늄하이드록사이드, 스테아릭애씨드, 카프릴릴글라이콜, 글리세릴카프릴레이트, 마데카소사이드, 판테놀, 말토덱스트린, 안하이드로자일리톨, 정제수, 글루코오스, 비에이치티, 향료, 티타늄디옥사이드(CI 77891)"
FIX[P('119')]=K[P('119')]['전성분'].replace('피브이엠/엠에이에코폴리머','피브이엠/엠에이코폴리머')
FIX[P('159')]=K[P('159')]['전성분'].replace('2, 3-부탄다이올','2,3-부탄다이올').replace('다이에틸헥실2, 6-나프탈레이트','다이에틸헥실2,6-나프탈레이트')
NOTE.update({P('076'):'Spelling fixed (사이클로헥사실록세인). Same product as 151; 151\'s 팥뿌리추출물 is a misreading of 뽕나무뿌리추출물.',
 P('077'):'Corrected: MUSE followed the EWG grade chart, not the 전성분 table (one extra item, two order errors). Confirmed by two independent readings (also under 150).',
 P('116'):'Replaced: the supplied list was a different formula. Label image: zinc oxide only; page says SPF40 PA+++, 18g (not SPF50+).',
 P('120'):'Replaced: the supplied list had 9 misreadings (e.g. 편백수(38%) not 판텐수(39%); two invented items).',
 P('173'):'Replaced: the supplied list was assumed from 126 and is a different formula. Label image list used (TiO2 + organic filters, BHT, fragrance).',
 P('122'):'The page prints "다이메티콘/비닐다이메티레이트" (apparent misprint); recorded as 다이메티콘/비닐다이메티콘.',
 P('013'):'One percentage on the image is blurry: 데하이드로아세틱애씨드 0.06% (reads as 0.06 or 0.05).',
 P('157'):'상품고시 says 기능성 여부: 해당 없음 (not a registered functional cosmetic), although the name claims SPF35 PA++.',
 P('158'):'상품고시 says 기능성 여부: 해당 없음, although the name claims SPF35 PA++. The print runs two pairs of items together; split as in the supplied list.',
 P('124'):'Page sells a set (본품 + 리필); list is for 순한 무기자차 선쿠션.',
 P('119'):'Typo fixed: 피브이엠/엠에이코폴리머. Image table names 야외놀이 워셔블 선크림 80ml (Cinnamoroll edition page).',
 P('080'):'Image prints 징크옥사이드 (CI 77947).'})
for i in ['080','081','082','083','121','123','124','155','156','157','159','119','146','158','013','122']: STATUS[P(i)]=('verified','label image on the official/retailer page; two independent readings agree')
for i in ['076','077','116','120','173']: STATUS[P(i)]=('verified (corrected)','label image; corrected list confirmed by two independent readings')

DUP={P('016'):P('137'),P('129'):P('111'),P('161'):P('126'),P('151'):P('076'),P('150'):P('077'),P('174'):P('120')}
rows=[]
for kid,k in K.items():
    sc=S[kid]
    full=FIX.get(kid,k['전성분'] or '')
    st,how=STATUS.get(kid,(None,None))
    if kid in DUP: st,how='duplicate',f'same product as {DUP[kid]}'
    elif st is None:
        if k['검수상태']=='user-verified': st,how='user verified','copied by hand from the Coupang product page (Angela)'
        elif sc['scope']=='exclude': st,how='not checked (out of scope)',k['검수상태']
        else: st,how='pending',{'global-formula-needs-kr-verification':'list taken from a foreign label; Korean label not found','derived-needs-human-check':'assumed same formula as a sibling; not confirmed (Kurly note suggests 173 differs)'}.get(k['검수상태'],'no official text found and the label image was not on the fetched page')
    uv=[(ko,inci) for ko,inci,_ in KR_UV if full and (find(full,ko,EXTRA_ALIASES.get(ko,())) or N(inci) in N(full))]
    oth=[inci for ko,inci in OTHER_UVA if full and (find(full,ko) or N(inci) in N(full))]
    kos={u[0] for u in uv}
    its=items(full)
    frag=any(re.fullmatch(r'향료|향|퍼퓸|fragrance|parfum',re.sub(r'[*+]','',x).strip(),re.I) for x in its)
    ALL=['리모넨','리날룰','시트로넬올','제라니올','시트랄','쿠마린','유제놀','벤질살리실레이트','헥실신남알','아밀신남알','하이드록시시트로넬알','알파-아이소메틸아이오논','벤질벤조에이트','부틸페닐메틸프로피오날','신남알','파네솔','벤질신나메이트','아이소유제놀','신나밀알코올','아니스알코올','에버니아프루나스트리추출물','에버니아푸르푸라세아추출물']
    alls=[a for a in ALL if any(N(a)==N(re.sub(r'[*+()0-9ppm.]','',x)) for x in its)]
    spf=k['SPF']; 
    if kid==P('145'): spf='SPF44'
    if kid==P('116'): spf='SPF40'
    rows.append({'ID':kid,'브랜드':k['브랜드'],'Brand':k['brand_en'],'제품명':k['제품명'],'용량':('13ml' if kid==P('160') else ('18g' if kid==P('116') else k['용량'])),'SPF':spf,'PA':('PA+++' if kid==P('116') else k['PA']),
      'Scope':sc['scope'],'Scope reason':sc['scope_reason'],'Verification':st,'Verification basis':how,'Correction / note':NOTE.get(kid,''),
      '전성분 (verified)':full,'Ingredient count':len(its),
      'UV filters (KR list)':', '.join(u[0] for u in uv),'UV filters (INCI)':', '.join(u[1] for u in uv),
      'Mineral only (ZnO/TiO2 only)':('' if not full else ('Yes' if kos and kos<=MIN else 'No')),
      'Mineral only (MUSE)':k['미네랄온리'],'Other UV absorbers in list':', '.join(oth),
      'Fragrance listed':('' if not full else ('Yes' if frag else 'No')),'Named fragrance allergens':', '.join(alls),
      'Source URL (MUSE)':k['출처URL'],'Coupang URL':k['쿠팡URL'],'Captured':k['수집일']})
json.dump(rows,open('/tmp/claude-0/krw/final_rows.json','w'),ensure_ascii=False,indent=0)
c=collections.Counter((r['Scope'],r['Verification']) for r in rows)
for x,n in sorted(c.items()): print(x,n)
inc=[r for r in rows if r['Scope']=='include' and r['Verification'] in ('verified','verified (corrected)','user verified')]
print('usable',len(inc),'mineral',sum(r['Mineral only (ZnO/TiO2 only)']=='Yes' for r in inc))
print('mineral flag changed vs MUSE:',[(r['ID'][-3:],r['Mineral only (MUSE)'],r['Mineral only (ZnO/TiO2 only)']) for r in rows if r['Mineral only (ZnO/TiO2 only)'] and (r['Mineral only (ZnO/TiO2 only)']=='Yes')!=(r['Mineral only (MUSE)']=='O')])
