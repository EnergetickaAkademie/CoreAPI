from collections import defaultdict
from MeritOrder import MeritOrder, Power
from typing import List, Tuple, Dict
import numpy as np
import json
from copy import deepcopy

prices = {
	Power.COAL: 101,
	Power.GAS: 132,
	Power.NUCLEAR: 15,
	Power.WATER: 0,
	Power.WATER_STORAGE: 0,
	Power.WIND: 0,
	Power.PHOTOVOLTAIC: 0,
	Power.BATTERY: 0,
}

co2eq = {
	Power.COAL: 1,
	Power.GAS: 0.5,
	Power.NUCLEAR: 0,
	Power.WATER: 0,
	Power.WATER_STORAGE: 0,
	Power.WIND: 0,
	Power.PHOTOVOLTAIC: 0,
	Power.BATTERY: 0,
}

BALANCE_CUTOFF_PERCENT = 1 #percent

MAX_POPULARITY_MW = 5210

def get_team_stats(history):
	team_stats = defaultdict()

	for t in history[0]:
		team_stats[t] = dict()
		team_stats[t]["productions"] = []
		team_stats[t]["consumptions"] = []
	
	for r in history: #for each round
		for team in r:
			team_stats[team]["productions"].append(r[team]["productions"])
			team_stats[team]["consumptions"].append(r[team]["total_consumption"])

	return team_stats

def get_last_building_consumption(team_stats, team):
	return team_stats[team]["consumptions"][-1]

def get_num_rounds(history):
	return len(history)

def get_teams(history):
	return list(history[0].keys())

def get_total_consumption(team_stats, team):
	return np.sum(team_stats[team]["consumptions"])

def get_min_co2():
	return 0

def get_max_co2(team_stats, team):
	total_cons = get_total_consumption(team_stats, team)
	return co2eq[Power.COAL] * total_cons

def get_co2(team_stats, team):
	consumptions = team_stats[team]["consumptions"]
	productions = team_stats[team]["productions"]

	co2 = []

	for (c, p) in zip(consumptions, productions):
		mo = MeritOrder(prices, p, c)
		co2.append(mo.getReleasedCO2())

	return np.sum(co2)

def get_ecology_score(team_stats, team):
	min_co2 = get_min_co2()
	max_co2 = get_max_co2(team_stats, team)
	co2 = get_co2(team_stats, team)

	if max_co2 == min_co2:
		return 100.0
	
	score = 100 * (1 - (co2 - min_co2) / (max_co2 - min_co2))

	return max(0, min(100, score))

def get_max_price(team_stats, team):
	total_cons = get_total_consumption(team_stats, team)
	return prices[Power.GAS] * total_cons

def get_expenses(team_stats, team):
	consumptions = team_stats[team]["consumptions"]
	productions = team_stats[team]["productions"]

	expenses = []

	for (c, p) in zip(consumptions, productions):
		mo = MeritOrder(prices, p, c)
		expenses.append(mo.getTotalExpenses())

	return np.sum(expenses)

def get_min_price():
	return 0

def get_finances_score(team_stats, team):
	min_exp = get_min_price()
	max_exp = get_max_price(team_stats, team)
	exp = get_expenses(team_stats, team)

	if max_exp == min_exp:
		return 100.0
	
	score = 100 * (1 - (exp - min_exp) / (max_exp - min_exp))

	return max(0, min(100, score))

def get_prod_sums(prod):
	res = []
	
	for p in prod:
		res.append(sum(x for _,x in p))

	return res

def get_prod_diffs(team_stats, team):
	consumptions = np.array(team_stats[team]["consumptions"])
	productions = np.array(get_prod_sums(team_stats[team]["productions"]))

	return (consumptions - productions), consumptions, productions

def get_balance(team_stats, team, num_rounds):
	pd, c, p = get_prod_diffs(team_stats, team)

	one_round = 1 / num_rounds

	one_perc = []

	for r in c:
		one_perc.append(BALANCE_CUTOFF_PERCENT * 0.01 * r)

	balance_stats = []

	for pdif, op in zip(pd, one_perc):
		if abs(pdif) <= 1:
			balance_stats.append(one_round)
		
		elif abs(pdif) > op:
			balance_stats.append(0)

		else:
			err = (abs(pdif) / op) * one_round if op != 0 else 0

			balance_stats.append(err)

		#print(f"op: {op}, abspdif: {abs(pdif)}")

	#print(f"bs: {balance_stats}")

	return balance_stats

def get_balance_score(team_stats, team, num_rounds):
	bal = get_balance(team_stats, team, num_rounds)

	return np.sum(bal)

def get_max_building_popularity():
	return MAX_POPULARITY_MW

def get_min_building_popularity():
	return 0

def get_building_popularity(team_stats, team):
	min_pop = get_min_building_popularity()
	max_pop = get_max_building_popularity()

	pop = get_total_consumption(team_stats, team)

	if max_pop == min_pop:
		return 100.0

	score = 100 * (pop - min_pop) / (max_pop - min_pop)

	return max(0, min(100, score))

def get_scores(team_stats, team, num_rounds):
	emx = get_balance_score(team_stats, team, num_rounds) * 100
	fin = get_finances_score(team_stats, team)
	eco = get_ecology_score(team_stats, team)
	pop = (emx + 2 * fin + eco + 2 * get_building_popularity(team_stats, team)) / 6 #0 - 100
	
	return {
		"emx" : round(emx, 2),
		"fin" : round(fin, 2),
		"eco" : round(eco, 2),
		"pop" : round(pop, 2),
	}

def calculate_final_scores(history):
	import sys
	print(f"history = {history}", file=sys.stderr)

	ts = get_team_stats(history)
	teams = get_teams(history)

	num_rounds = get_num_rounds(history)

	scores = dict()

	for t in teams:
		scores[t] = get_scores(ts, t, num_rounds)

	return scores


if __name__ == "__main__":
	# history = [
	# 	# --- Round 1 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 1500), (Power.WIND, 100)], 'total_consumption': 1600},
	# 		"Team B": {'productions': [(Power.COAL, 1000), (Power.GAS, 800)], 'total_consumption': 1800},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 800), (Power.GAS, 400), (Power.WIND, 100)], 'total_consumption': 1300},
	# 		"Team D": {'productions': [(Power.WATER, 2500)], 'total_consumption': 2000},
	# 		"Team E": {'productions': [(Power.WIND, 1200), (Power.PHOTOVOLTAIC, 400)], 'total_consumption': 1500},
	# 	},
	# 	# --- Round 2 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 1500), (Power.WIND, 300)], 'total_consumption': 1800},
	# 		"Team B": {'productions': [(Power.COAL, 1200), (Power.GAS, 800)], 'total_consumption': 2000},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 800), (Power.GAS, 500), (Power.WIND, 200)], 'total_consumption': 1500},
	# 		"Team D": {'productions': [(Power.WATER, 2500)], 'total_consumption': 2200},
	# 		"Team E": {'productions': [(Power.WIND, 1400), (Power.PHOTOVOLTAIC, 600)], 'total_consumption': 1700}, # Barely meeting demand
	# 	},
	# 	# --- Round 3 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 1500), (Power.WIND, 500), (Power.PHOTOVOLTAIC, 10)], 'total_consumption': 2000},
	# 		"Team B": {'productions': [(Power.COAL, 1300), (Power.GAS, 900)], 'total_consumption': 2200},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 900), (Power.GAS, 500), (Power.WIND, 300)], 'total_consumption': 1700},
	# 		"Team D": {'productions': [(Power.WATER, 2500), (Power.GAS, 100)], 'total_consumption': 2400}, # Demand exceeds hydro
	# 		"Team E": {'productions': [(Power.WIND, 1000), (Power.PHOTOVOLTAIC, 400)], 'total_consumption': 1900}, # BLACKOUT!
	# 	},
	# 	# --- Round 4 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 2000), (Power.WIND, 500)], 'total_consumption': 2200}, # New nuclear plant
	# 		"Team B": {'productions': [(Power.COAL, 1500), (Power.GAS, 1000)], 'total_consumption': 2400},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 900), (Power.GAS, 600), (Power.WIND, 400)], 'total_consumption': 1900},
	# 		"Team D": {'productions': [(Power.WATER, 2500), (Power.GAS, 300)], 'total_consumption': 2600},
	# 		"Team E": {'productions': [(Power.WIND, 2000), (Power.PHOTOVOLTAIC, 800)], 'total_consumption': 2100},
	# 	},
	# 	# --- Round 5 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 2000), (Power.WIND, 700), (Power.PHOTOVOLTAIC, 100)], 'total_consumption': 2400},
	# 		"Team B": {'productions': [(Power.COAL, 1600), (Power.GAS, 1100)], 'total_consumption': 2600},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 1000), (Power.GAS, 600), (Power.WIND, 500)], 'total_consumption': 2100},
	# 		"Team D": {'productions': [(Power.WATER, 2500), (Power.GAS, 500)], 'total_consumption': 2800},
	# 		"Team E": {'productions': [(Power.WIND, 1500), (Power.PHOTOVOLTAIC, 600), (Power.GAS, 100)], 'total_consumption': 2300}, # Added a gas peaker
	# 	},
	# 	# --- Round 6 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 2000), (Power.WIND, 900), (Power.PHOTOVOLTAIC, 300)], 'total_consumption': 2600},
	# 		"Team B": {'productions': [(Power.COAL, 1800), (Power.GAS, 1200)], 'total_consumption': 2800},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 1000), (Power.GAS, 700), (Power.WIND, 600)], 'total_consumption': 2300},
	# 		"Team D": {'productions': [(Power.WATER, 2500), (Power.COAL, 500)], 'total_consumption': 3000}, # Built a coal plant
	# 		"Team E": {'productions': [(Power.WIND, 1200), (Power.PHOTOVOLTAIC, 500), (Power.GAS, 100)], 'total_consumption': 2500}, # BLACKOUT!
	# 	},
	# 	# --- Round 7 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 2500), (Power.WIND, 1000)], 'total_consumption': 2800}, # Another nuclear plant
	# 		"Team B": {'productions': [(Power.COAL, 2000), (Power.GAS, 1200)], 'total_consumption': 3000},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 1200), (Power.GAS, 700), (Power.WIND, 700)], 'total_consumption': 2500},
	# 		"Team D": {'productions': [(Power.WATER, 2500), (Power.COAL, 800)], 'total_consumption': 3200},
	# 		"Team E": {'productions': [(Power.WIND, 2500), (Power.PHOTOVOLTAIC, 1000), (Power.GAS, 200)], 'total_consumption': 2700},
	# 	},
	# 	# --- Round 8 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 2500), (Power.WIND, 1200), (Power.PHOTOVOLTAIC, 300)], 'total_consumption': 3000},
	# 		"Team B": {'productions': [(Power.COAL, 2200), (Power.GAS, 1300)], 'total_consumption': 3200},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 1200), (Power.GAS, 800), (Power.WIND, 800)], 'total_consumption': 2700},
	# 		"Team D": {'productions': [(Power.WATER, 2500), (Power.COAL, 1000)], 'total_consumption': 3400},
	# 		"Team E": {'productions': [(Power.WIND, 1800), (Power.PHOTOVOLTAIC, 800), (Power.GAS, 200)], 'total_consumption': 2900}, # Another blackout!
	# 	},
	# 	# --- Round 9 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 2500), (Power.WIND, 1500), (Power.PHOTOVOLTAIC, 400)], 'total_consumption': 3200},
	# 		"Team B": {'productions': [(Power.COAL, 2400), (Power.GAS, 1400)], 'total_consumption': 3400},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 1200), (Power.GAS, 900), (Power.WIND, 900)], 'total_consumption': 2900},
	# 		"Team D": {'productions': [(Power.WATER, 2500), (Power.COAL, 1200)], 'total_consumption': 3600},
	# 		"Team E": {'productions': [(Power.WIND, 3000), (Power.PHOTOVOLTAIC, 1200), (Power.GAS, 200)], 'total_consumption': 3100},
	# 	},
	# 	# --- Round 10 ---
	# 	{
	# 		"Team A": {'productions': [(Power.NUCLEAR, 3000), (Power.WIND, 1500)], 'total_consumption': 3400},
	# 		"Team B": {'productions': [(Power.COAL, 2500), (Power.GAS, 1500)], 'total_consumption': 3600},
	# 		"Team C": {'productions': [(Power.NUCLEAR, 1500), (Power.GAS, 1000), (Power.WIND, 1000)], 'total_consumption': 3100},
	# 		"Team D": {'productions': [(Power.WATER, 2500), (Power.COAL, 1500)], 'total_consumption': 3800},
	# 		"Team E": {'productions': [(Power.WIND, 2000), (Power.PHOTOVOLTAIC, 1000), (Power.GAS, 500)], 'total_consumption': 3300},
	# 	},
	# ]

	history = [
		{
			"Team A": {'productions': [(Power.NUCLEAR, 1500), (Power.WIND, 100)], 'total_consumption': 1600.5},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 1500), (Power.WIND, 300)], 'total_consumption': 1800},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 1500), (Power.WIND, 500), (Power.PHOTOVOLTAIC, 100)], 'total_consumption': 2100.5},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 2000), (Power.WIND, 500)], 'total_consumption': 2505},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 2000), (Power.WIND, 700), (Power.PHOTOVOLTAIC, 100)], 'total_consumption': 2800},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 2000), (Power.WIND, 900), (Power.PHOTOVOLTAIC, 300)], 'total_consumption': 3200.5},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 2500), (Power.WIND, 1000)], 'total_consumption': 3500},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 2500), (Power.WIND, 1200), (Power.PHOTOVOLTAIC, 300)], 'total_consumption': 4000.5},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 2900), (Power.WIND, 1500), (Power.PHOTOVOLTAIC, 400), (Power.BATTERY, -400)], 'total_consumption': 4400},
		},
		{
			"Team A": {'productions': [(Power.NUCLEAR, 3000), (Power.WIND, 1500)], 'total_consumption': 4460},
		},
	]

	history = [{'Team 1': {'productions': [(Power.COAL, 1000.0)], 'total_consumption': 1000}}, {'Team 1': {'productions': [(Power.COAL, 1000.0)], 'total_consumption': 1002}}, {'Team 1': {'productions': [(Power.COAL, 1000.0)], 'total_consumption': 1000}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0)], 'total_consumption': 1200}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0)], 'total_consumption': 1200}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0), (Power.GAS, 200.0)], 'total_consumption': 1605}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0), (Power.GAS, 200.0)], 'total_consumption': 1605}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0), (Power.GAS, 200.0), (Power.WIND, 200.0), (Power.PHOTOVOLTAIC, 405.0)], 'total_consumption': 1605}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0), (Power.GAS, 200.0), (Power.WIND, 200.0), (Power.PHOTOVOLTAIC, 405.0)], 'total_consumption': 1605}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0), (Power.GAS, 200.0), (Power.WIND, 200.0), (Power.PHOTOVOLTAIC, 405.0)], 'total_consumption': 1605}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0), (Power.GAS, 200.0), (Power.WIND, 200.0), (Power.PHOTOVOLTAIC, 405.0)], 'total_consumption': 1605}}, {'Team 1': {'productions': [(Power.COAL, 100.0), (Power.NUCLEAR, 1000.0), (Power.GAS, 200.0), (Power.WIND, 200.0), (Power.PHOTOVOLTAIC, 405.0)], 'total_consumption': 1605}}]
	
	history = [{'Team 5': {'productions': [(Power.GAS, 420.0)], 'total_consumption': 420.0}},
			{'Team 5': {'productions': [(Power.GAS, 420.0)], 'total_consumption': 420.0}},
			{'Team 5': {'productions': [(Power.GAS, 419.9)], 'total_consumption': 420.0}},
			{'Team 5': {'productions': [(Power.GAS, 290.4)], 'total_consumption': 290.0}},
			{'Team 5': {'productions': [(Power.GAS, 980.0)], 'total_consumption': 980.0}},
			{'Team 5': {'productions': [(Power.GAS, 950.0)], 'total_consumption': 760.0}},
			{'Team 5': {'productions': [(Power.GAS, 1201.0)], 'total_consumption': 980.0}},
			{'Team 5': {'productions': [(Power.GAS, 1201.0)], 'total_consumption': 760.0}},
			{'Team 5': {'productions': [(Power.GAS, 1201.0)], 'total_consumption': 980.0}},
			{'Team 5': {'productions': [(Power.GAS, 1201.0)], 'total_consumption': 760.0}},
			{'Team 5': {'productions': [(Power.GAS, 1201.0)], 'total_consumption': 760.0}},
			{'Team 5': {'productions': [(Power.GAS, 1001.0)], 'total_consumption': 760.0}},
			{'Team 5': {'productions': [(Power.GAS, 980.399)], 'total_consumption': 980.0}},
			{'Team 5': {'productions': [(Power.GAS, 950.0)], 'total_consumption': 760.0}}]

	final_scores = calculate_final_scores(history)

	print(f"fs: {final_scores}")