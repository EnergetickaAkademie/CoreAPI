from enum import Enum

from typing import List, Tuple
import numpy as np

class Power(Enum):
	COAL = 0
	GAS = 1
	NUCLEAR = 2
	WATER = 3
	WATER_STORAGE = 4
	WIND = 5
	PHOTOVOLTAIC = 6
	BATTERY = 7

	def __repr__(self):
		return f"Power.{self.name}"
	
	def __str__(self):
		return f"Power.{self.name}"

class MeritOrder:
	def __init__(self, prices: dict[Power, float], productions: List[Tuple[Power, float]], total_consumption: float):
		self.prices = prices
		
		# Convert productions to a proper format for numpy
		if productions:
			# Create a structured array or handle as list of tuples
			self.productions = productions  # Keep as list for now
			# Sort by price and ensure proper 2D structure
			sorted_prods = sorted(productions, key=lambda x: self.prices[x[0]])
			# Create 2D array explicitly: [[power_enum, value], [power_enum, value], ...]
			self.sorted_productions = np.array([[prod[0], prod[1]] for prod in sorted_prods], dtype=object)
		else:
			self.productions = []
			self.sorted_productions = np.array([]).reshape(0, 2)
			
		self.total_consumption = total_consumption
		self.co2eq = {
			Power.COAL: 1,
			Power.GAS: 0.5,
			Power.NUCLEAR: 0,
			Power.WATER: 0,
			Power.WATER_STORAGE: 0,
			Power.WIND: 0,
			Power.PHOTOVOLTAIC: 0,
			Power.BATTERY: 0,
		}

		self.derating = {
			Power.COAL: 87.9,
			Power.GAS: 95,
			Power.NUCLEAR: 92.1,
			Power.WATER: 41,
			Power.WATER_STORAGE: 41,
			Power.WIND: 7.3,
			Power.PHOTOVOLTAIC: 2.7,
			Power.BATTERY: 0.0,
		}

	def getPrice(self):
		'''Get the current price of power in EUR/MWh, by ordering the powerplant according to the merit order, and getting the lowest price that satisfies the total consumption.'''
	
		cmsm = np.cumsum(self.sorted_productions[:, 1])

		for idx, el in enumerate(cmsm):
			if el >= self.total_consumption:
				return self.prices[self.sorted_productions[idx][0]]

		return 0

	def getTotalCost(self):
		'''Get the total cost of electricity production with the current consumption total.'''
		price_per_mwh = self.getPrice()

		return price_per_mwh * self.total_consumption

	def getTotalProfit(self):
		'''Get total profit in EUR for all the powerplants, that produce, with a given consumption.'''

		price = self.getPrice()

		cmsm = np.cumsum(self.sorted_productions[:, 1])

		total = 0

		for idx, el in enumerate(cmsm):
			if el >= self.total_consumption:
				pp_type, _ = self.sorted_productions[idx]
				pp_price = self.prices[pp_type]

				production = self.total_consumption - cmsm[idx - 1] #the previous cumsum element

				pp_selling_cost = production * price
				pp_operating_cost = production * pp_price

				total += pp_selling_cost - pp_operating_cost #profit for powerplant

				break

			else:
				pp_type, pp_power = self.sorted_productions[idx]
				pp_price = self.prices[pp_type]

				pp_selling_cost = pp_power * price
				pp_operating_cost = pp_power * pp_price

				total += pp_selling_cost - pp_operating_cost #profit for powerplant

		return total
	
	def getTotalExpenses(self):
		# Handle empty productions case
		if len(self.sorted_productions) == 0:
			return 0
			
		cmsm = np.cumsum(self.sorted_productions[:, 1])

		total = 0

		for idx, el in enumerate(cmsm):
			if el >= self.total_consumption:
				pp_type, _ = self.sorted_productions[idx]

				production = self.total_consumption - (cmsm[idx - 1] if idx > 0 else 0) #the previous cumsum element

				total += production * self.prices[pp_type]

				break

			else:
				pp_type, pp_power = self.sorted_productions[idx]

				total += pp_power * self.prices[pp_type]

		return total
	
	def getReleasedCO2(self):
		'''Get the amount of released CO2 eq. (in tonnes).'''
		
		# Handle empty productions case
		if len(self.sorted_productions) == 0:
			return 0

		cmsm = np.cumsum(self.sorted_productions[:, 1])

		total = 0

		for idx, el in enumerate(cmsm):
			if el >= self.total_consumption:
				pp_type, _ = self.sorted_productions[idx]

				production = self.total_consumption - (cmsm[idx - 1] if idx > 0 else 0) #the previous cumsum element

				total += production * self.co2eq[pp_type]

				break

			else:
				pp_type, pp_power = self.sorted_productions[idx]

				total += pp_power * self.co2eq[pp_type]

		return total
	
	def getGridStability(self):
		'''Get the grid stability coefficient.'''

		if self.total_consumption <= 0:
			return 100.0
			
		# Handle empty productions case
		if len(self.sorted_productions) == 0:
			return 0.0

		cmsm = np.cumsum(self.sorted_productions[:, 1])
		weighted_stability_sum = 0

		previous_sum = 0

		for idx, el in enumerate(cmsm):
			if el >= self.total_consumption:
				pp_type, _ = self.sorted_productions[idx]
				
				production_from_this_plant = self.total_consumption - previous_sum
				
				weighted_stability_sum += production_from_this_plant * self.derating[pp_type]
				
				break
			
			else:
				pp_type, pp_power = self.sorted_productions[idx]
				
				weighted_stability_sum += pp_power * self.derating[pp_type]

				previous_sum = el
				
		return weighted_stability_sum / self.total_consumption


if __name__ == "__main__":
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

	productions = [
		(Power.COAL, 300),
		(Power.COAL, 400),
		(Power.GAS, 200),
		(Power.NUCLEAR, 1000),
		(Power.WATER, 50),
		(Power.WIND, 100),
		(Power.PHOTOVOLTAIC, 50),
	]
	
	total_consumption = 1201

	mo = MeritOrder(prices, productions, total_consumption)

	print(f"price: {mo.getPrice()} EUR/MWh")
	print(f"cost: {mo.getTotalCost()} EUR")
	print(f"profit: {mo.getTotalProfit()} EUR")
	print(f"emissions: {mo.getReleasedCO2()} t CO2eq.")
	print(f"stability: {mo.getGridStability()}")