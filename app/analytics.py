from sqlalchemy import text

from .ingestion.scorecards import overs

# Byte-order collation keeps name ordering identical to the previous SQLite (BINARY) behaviour.
C='COLLATE "C"'
# Optional tournament filter; :tour is NULL for all tournaments.
TF='(CAST(:tour AS integer) IS NULL OR m.tournament_id=:tour)'

def records(db,sql,args=None):return [dict(r) for r in db.execute(text(sql),args or {}).mappings()]
def teams(db,tournament=None):
 ts=records(db,'SELECT t.*, (SELECT count(*) FROM roster_entries r WHERE r.team_id=t.id) club_listings,(SELECT count(*) FROM innings i JOIN matches m ON m.id=i.match_id WHERE i.team_id=t.id AND '+TF+') played,(SELECT count(*) FROM matches m WHERE m.winner=t.id AND '+TF+') wins FROM teams t ORDER BY name '+C,{'tour':tournament})
 for t in ts:t['losses']=t['played']-t['wins']
 return ts

def players(db,team=None,tournament=None):
 ps=records(db,'SELECT * FROM players ORDER BY name '+C)
 bats=records(db,'SELECT b.*,i.team_id,m.date FROM batting b JOIN innings i ON i.match_id=b.match_id AND i.number=b.innings_number JOIN matches m ON m.id=b.match_id WHERE '+TF,{'tour':tournament})
 bowls=records(db,'SELECT b.*, CASE WHEN b.innings_number=1 THEN m.team2 ELSE m.team1 END team_id,m.date FROM bowling b JOIN matches m ON m.id=b.match_id WHERE '+TF,{'tour':tournament})
 out=[];tn={t['id']:t['name'] for t in teams(db)}
 for p in ps:
  ba=[r for r in bats if r['player_id']==p['id'] and (not team or r['team_id']==team)]
  bo=[r for r in bowls if r['player_id']==p['id'] and (not team or r['team_id']==team)]
  if not ba and not bo:continue
  runs=sum(r['runs'] for r in ba);balls=sum(r['balls'] for r in ba);dismissals=sum(not r['not_out'] for r in ba)
  br=sum(r['runs'] for r in bo);bb=sum(r['balls'] for r in bo);wk=sum(r['wickets'] for r in bo)
  tids=sorted(set(r['team_id'] for r in ba+bo))
  p.update(innings=len([r for r in ba if r['balls']>0 or r['runs']>0 or not r['not_out']]),runs=runs,balls=balls,dismissals=dismissals,average=round(runs/dismissals,2) if dismissals else None,strike_rate=round(runs*100/balls,2) if balls else None,fours=sum(r['fours'] for r in ba),sixes=sum(r['sixes'] for r in ba),high_score=max([r['runs'] for r in ba],default=None),wickets=wk,bowling_runs=br,bowling_balls=bb,economy=round(br*6/bb,2) if bb else None,bowling_dots=sum(r['dots'] for r in bo),overs=overs(bb),teams=[tn[t] for t in tids],team_ids=tids,matches=len(set(r['match_id'] for r in ba+bo)),form=[r['runs'] for r in sorted(ba,key=lambda r:(r['date'],r['match_id'])) if r['balls']>0 or r['runs']>0 or not r['not_out']])
  boundary_runs=p['fours']*4+p['sixes']*6;p['boundary_run_pct']=round(boundary_runs/runs*100,1) if runs else None
  out.append(p)
 return out

def match_list(db,team=None,tournament=None):
 sql='SELECT m.*,a.name team1_name,b.name team2_name,tr.name tournament_name FROM matches m JOIN teams a ON a.id=m.team1 JOIN teams b ON b.id=m.team2 JOIN tournaments tr ON tr.id=m.tournament_id WHERE '+TF
 args={'tour':tournament}
 if team:sql+=' AND (m.team1=:team OR m.team2=:team)';args['team']=team
 ms=records(db,sql+' ORDER BY m.date DESC,m.id '+C+' DESC',args)
 for m in ms:
  m['innings']=records(db,'SELECT i.*,t.name team_name FROM innings i JOIN teams t ON t.id=i.team_id WHERE match_id=:m ORDER BY number',{'m':m['id']})
  for inn in m['innings']:inn['overs']=overs(inn['balls']);inn['run_rate']=round(inn['runs']*6/inn['balls'],2) if inn['balls'] else None
 return ms

def match_detail(db,mid):
 m=next((m for m in match_list(db) if m['id']==mid),None)
 if m:m['max_balls']=db.execute(text('SELECT overs_per_innings*6 FROM tournaments WHERE id=:t'),{'t':m['tournament_id']}).scalar()
 if not m:return None
 for inn in m['innings']:
  args={'m':mid,'n':inn['number']}
  inn['batting']=records(db,'SELECT b.*,p.name FROM batting b JOIN players p ON p.id=b.player_id WHERE match_id=:m AND innings_number=:n ORDER BY position',args)
  inn['bowling']=records(db,'SELECT b.*,p.name FROM bowling b JOIN players p ON p.id=b.player_id WHERE match_id=:m AND innings_number=:n ORDER BY position',args)
  for b in inn['batting']:b['strike_rate']=round(b['runs']*100/b['balls'],2) if b['balls'] else None
  for b in inn['bowling']:b['overs']=overs(b['balls']);b['economy']=round(b['runs']*6/b['balls'],2) if b['balls'] else None
  inn['fall_of_wickets']=records(db,'SELECT wicket,runs,balls,batter FROM fall_of_wickets WHERE match_id=:m AND innings_number=:n ORDER BY wicket',args)
 return m

def profile(db,pid,team=None,tournament=None):
 p=next((p for p in players(db,team,tournament) if p['id']==pid),None)
 if not p:return None
 p['batting_history']=records(db,'SELECT b.*,m.date,m.source_url,t.name team_name FROM batting b JOIN matches m ON m.id=b.match_id JOIN innings i ON i.match_id=b.match_id AND i.number=b.innings_number JOIN teams t ON t.id=i.team_id WHERE player_id=:p AND '+TF+(' AND i.team_id=:team' if team else '')+' ORDER BY m.date,m.id '+C,{'p':pid,'team':team,'tour':tournament})
 p['bowling_history']=records(db,'SELECT b.*,m.date,m.source_url FROM bowling b JOIN matches m ON m.id=b.match_id WHERE player_id=:p AND '+TF+(' AND CASE WHEN b.innings_number=1 THEN m.team2 ELSE m.team1 END=:team' if team else '')+' ORDER BY m.date,m.id '+C,{'p':pid,'team':team,'tour':tournament})
 for b in p['bowling_history']:b['overs']=overs(b['balls'])
 insights=[]
 if p['innings']<3:insights.append(f"Only {p['innings']} batting innings covered. This is too little to infer a stable weakness or form trend.")
 if p['runs'] and p['boundary_run_pct'] is not None:insights.append(f"{p['boundary_run_pct']}% of recorded batting runs came from fours and sixes. This measures scoring composition, not shot placement.")
 if pid=='32722355':insights.append('In the imported 3 Oct match you scored 0 from 4 balls, caught off Rajesh Kharche. The scorecard does not show line, length or shot selection. A technical diagnosis needs video or ball events.')
 if p['bowling_balls']:insights.append(f"Recorded bowling: {p['wickets']} wickets from {overs(p['bowling_balls'])} overs, economy {p['economy']}. Compare opponents and match conditions before drawing conclusions.")
 p['insights']=insights
 # Only provider-identified players have a CricHeroes profile; PDF-created players do not.
 p['source_url']=f'https://cricheroes.com/player-profile/{pid}/'+p['name'].lower().replace(' ','-')+'/matches' if p.get('provider')=='cricheroes' else None
 return p

def summary(db,team=None,tournament=None):
 ms=match_list(db,team,tournament);ps=players(db,team,tournament);ts=teams(db,tournament)
 runs=sum(i['runs'] for m in ms for i in m['innings'] if not team or i['team_id']==team)
 return dict(teams=ts,completed=len(ms),recorded_runs=runs,batting_players=len([p for p in ps if p['innings']]),roster_entries=db.execute(text('SELECT count(*) FROM roster_entries')).scalar_one(),matches=ms,batting_leaders=sorted(ps,key=lambda p:(-p['runs'],p['name']))[:5],bowling_leaders=sorted([p for p in ps if p['bowling_balls']],key=lambda p:(-p['wickets'],p['economy']))[:5],coverage=coverage(db))

def tournaments(db):
 return records(db,'SELECT tr.id,tr.provider,tr.kind,tr.external_id,tr.name,tr.slug,tr.overs_per_innings,tr.max_overs_per_bowler,count(m.id) matches,min(m.date) first_match,max(m.date) last_match FROM tournaments tr LEFT JOIN matches m ON m.tournament_id=tr.id GROUP BY tr.id ORDER BY tr.name '+C)

def coverage(db):
 return dict(completed_scorecards=db.execute(text('SELECT count(*) FROM matches')).scalar_one(),tournaments=tournaments(db),rosters='Public club listings; not confirmed tournament squads',ball_by_ball=False,live_sync=False)

def coach(db,pid,question):
 p=profile(db,pid)
 if not p:return 'Select a player with an imported scorecard.'
 q=question.lower();base=f"{p['name']}: {p['runs']} runs from {p['balls']} balls across {p['innings']} recorded batting innings. "
 if any(w in q for w in ['bowl','economy','wicket']):return f"{p['name']} has {p['wickets']} wickets from {p['overs']} recorded overs. "+('Economy is '+str(p['economy'])+'. ' if p['economy'] is not None else '')+'These are imported scorecard totals; pace/spin and phase comparisons need ball events.'
 if any(w in q for w in ['out','weak','improve','bat']):return base+' '.join(p['insights'])+' General practice suggestion: rehearse a controlled first ten balls, then practice singles into gaps. This drill is general guidance, not an inferred technical fix.'
 return base+f"Recorded strike rate: {p['strike_rate'] if p['strike_rate'] is not None else 'unavailable'}. Average: {p['average'] if p['average'] is not None else 'undefined because there are no dismissals'}. "+'Analysis is limited to imported tournament scorecards. No video, shot zones or ball-by-ball data is available.'
