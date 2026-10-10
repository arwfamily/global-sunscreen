import json,re,collections,sys
K=json.load(open('/tmp/claude-0/krw/kr.json'))
def N(s):
    s=s.replace(' ','').replace('-','').replace('‐','').lower()
    for a,b in [('에틸','에칠'),('메틸','메칠'),('다이','디'),('트라이','트리'),('아이소','이소'),('애시드','애씨드'),('벤조트리아졸릴','벤조트리아졸릴'),('바이페닐','비페닐'),('아미노','아미노'),('메테인','메탄'),('다이벤조일','디벤조일'),('트리아존','트리아존')]: s=s.replace(a,b)
    return s
# (Korean name, INCI, max %) — 기능성화장품 심사에 관한 규정 별표4 (27) + 2023/2024 designations
KR_UV=[('드로메트리졸','Drometrizole',1),('디갈로일트리올리에이트','Digalloyl Trioleate',5),('4-메칠벤질리덴캠퍼','4-Methylbenzylidene Camphor',4),('멘틸안트라닐레이트','Menthyl Anthranilate',5),('벤조페논-3','Benzophenone-3',5),('벤조페논-4','Benzophenone-4',5),('벤조페논-8','Benzophenone-8',3),('부틸메톡시디벤조일메탄','Butyl Methoxydibenzoylmethane',5),('시녹세이트','Cinoxate',5),('에칠헥실트리아존','Ethylhexyl Triazone',5),('옥토크릴렌','Octocrylene',10),('에칠헥실디메칠파바','Ethylhexyl Dimethyl PABA',8),('에칠헥실메톡시신나메이트','Ethylhexyl Methoxycinnamate',7.5),('에칠헥실살리실레이트','Ethylhexyl Salicylate',5),('페닐벤즈이미다졸설포닉애씨드','Phenylbenzimidazole Sulfonic Acid',4),('호모살레이트','Homosalate',10),('징크옥사이드','Zinc Oxide',25),('티타늄디옥사이드','Titanium Dioxide',25),('이소아밀p-메톡시신나메이트','Isoamyl p-Methoxycinnamate',10),('비스-에칠헥실옥시페놀메톡시페닐트리아진','Bis-Ethylhexyloxyphenol Methoxyphenyl Triazine',10),('디소듐페닐디벤즈이미다졸테트라설포네이트','Disodium Phenyl Dibenzimidazole Tetrasulfonate',10),('드로메트리졸트리실록산','Drometrizole Trisiloxane',15),('디에칠헥실부타미도트리아존','Diethylhexyl Butamido Triazone',10),('폴리실리콘-15','Polysilicone-15',10),('메칠렌비스-벤조트리아졸릴테트라메칠부틸페놀','Methylene Bis-Benzotriazolyl Tetramethylbutylphenol',10),('테레프탈릴리덴디캠퍼설포닉애씨드','Terephthalylidene Dicamphor Sulfonic Acid',10),('디에칠아미노하이드록시벤조일헥실벤조에이트','Diethylamino Hydroxybenzoyl Hexyl Benzoate',10),
 ('메톡시프로필아미노사이클로헥세닐리덴에톡시에칠사이아노아세테이트','Methoxypropylamino Cyclohexenylidene Ethoxyethylcyanoacetate',3),('트리스-비페닐트리아진','Tris-Biphenyl Triazine',None)]
EXTRA_ALIASES={'폴리실리콘-15':['디메치코디에칠벤잘말로네이트'],'메톡시프로필아미노사이클로헥세닐리덴에톡시에칠사이아노아세테이트':['메톡시프로필아미노사이클로헥시닐리덴에톡시에틸사이아노아세테이트'],'벤조페논-3':['옥시벤존']}
OTHER_UVA=[('벤조트리아졸릴도데실p-크레솔','Benzotriazolyl Dodecyl p-Cresol'),('부틸옥틸살리실레이트','Butyloctyl Salicylate'),('에칠헥실메톡시크릴렌','Ethylhexyl Methoxycrylene'),('폴리에스터-8','Polyester-8'),('디에칠헥실시린길리덴말로네이트','Diethylhexyl Syringylidenemalonate'),('트리데실살리실레이트','Tridecyl Salicylate'),('디에칠헥실2,6-나프탈레이트','Diethylhexyl 2,6-Naphthalate')]
MIN={'징크옥사이드','티타늄디옥사이드'}
def items(full):
    # split on commas not inside parentheses and not between digits (1,2-헥산다이올 / 10,000ppm)
    out,depth,cur=[],0,''
    for i,ch in enumerate(full):
        if ch in '([': depth+=1
        if ch in ')]': depth=max(0,depth-1)
        if ch==',' and depth==0 and not (i>0 and full[i-1].isdigit() and i+1<len(full) and full[i+1].isdigit()):
            out.append(cur.strip()); cur=''
        else: cur+=ch
    if cur.strip(): out.append(cur.strip())
    return [x for x in out if x]
def find(full,name,aliases=()):
    nf=N(full)
    return any(N(a) in nf for a in (name,)+tuple(aliases))
res=[]
for k in K:
    full=k['전성분'] or ''
    uv=[(ko,inci) for ko,inci,_ in KR_UV if full and (find(full,ko,EXTRA_ALIASES.get(ko,())) or N(inci) in N(full))]
    oth=[(ko,inci) for ko,inci in OTHER_UVA if full and (find(full,ko) or N(inci) in N(full))]
    kos={u[0] for u in uv}
    mineral_only = bool(kos) and kos<=MIN
    res.append({'ID':k['ID'],'uv_filters_ko':[u[0] for u in uv],'uv_filters_inci':[u[1] for u in uv],'other_uv_absorbers':[o[1] for o in oth],
                'mineral_only':mineral_only if full else None,'muse_mineral':k['미네랄온리'],'items':items(full)})
json.dump(res,open('/tmp/claude-0/krw/uv.json','w'),ensure_ascii=False,indent=0)
dis=[r for r in res if r['mineral_only'] is not None and (r['mineral_only']!=(r['muse_mineral']=='O'))]
print('disagree with Muse mineral flag:',len(dis))
for r in dis: print(' ',r['ID'][-3:],r['muse_mineral'],r['uv_filters_ko'],r['other_uv_absorbers'])
print('none found:',[r['ID'][-3:] for r in res if not r['uv_filters_ko']])
print('other absorbers:',collections.Counter(x for r in res for x in r['other_uv_absorbers']))
