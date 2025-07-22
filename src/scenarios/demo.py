from enak.Enak import *

building_consumptions = {
	#these numbers define the (day, night) consumption of the specific buildings
	Building.CITY_CENTER_A: (575, 200),
	Building.CITY_CENTER_B: (600, 200),
	Building.CITY_CENTER_C: (620, 200),
	Building.CITY_CENTER_D: (550, 200),
	Building.CITY_CENTER_E: (625, 200),
	Building.CITY_CENTER_F: (550, 200),
	
	Building.FACTORY: (400, 400),
	Building.STADIUM: (250, 400),
	Building.HOSPITAL: (350, 250),
	Building.UNIVERSITY: (400, 200),
	Building.AIRPORT: (500, 400),
	Building.SHOPPING_MALL: (350, 200),
	Building.TECHNOLOGY_CENTER: (300, 250),
	Building.FARM: (80, 40),
	Building.LIVING_QUARTER_SMALL: (70, 40),
	Building.LIVING_QUARTER_LARGE: (100, 60),
	Building.SCHOOL: (80, 30)
}

def getScript():
	script = Script(building_consumptions)

	script.setPDF("prednaska.pdf")

	#FÁZE 1 - prezentace
	sr = SlideRange(1, 5) #starting index is 1
	script.addRound(sr)
	#same for the other teams

	#FÁZE 2 - umístění dvou uhelek a jedné budovy, jednoduché vyrovnání soustavy
	script.allowProduction(Source.COAL)

	d = Day()
	script.addRound(d)

	n = Night()
	script.addRound(n)

	#FÁZE 3 - spotřeba města roste o 60MW ve dne, o 120MW v noci
	script.changeBuildingsConsumptions(CITY_CENTERS, (60, 120))
	script.allowProduction(Source.HYDRO)
	script.allowProduction(Source.HYDRO_STORAGE)

	d = Day()
	script.addRound(d)

	n = Night()
	script.addRound(n)

	#FÁZE 4 - jaderky, spotřeba roste o 100MW
	script.allowProduction(Source.NUCLEAR)
	script.changeBuildingsConsumptions(CITY_CENTERS, (100, 100))

	d = Day()
	script.addRound(d)

	n = Night()
	script.addRound(n)

	#FÁZE 5 - spotřeba města roste o 100MW, plynové elektrárny
	script.changeBuildingsConsumptions(CITY_CENTERS, (100, 100))
	script.allowProduction(Source.GAS)
	
	d = Day()
	script.addRound(d)

	n = Night()
	script.addRound(n)

	#FÁZE 6 - spotřeba města roste o 200 MW, nový typ OZE
	script.changeBuildingsConsumptions(CITY_CENTERS, (200, 200))
	script.allowProduction(Source.WIND)
	script.allowProduction(Source.PHOTOVOLTAIC)

	#normal calm day (average wind, average sun)
	d = Day()
	script.addRound(d)

	n = Night()
	script.addRound(n)

	#FÁZE 7 - scénáře

	d = Windy(Sunny(Day()))
	script.addRound(d)

	n = Windy(Night())
	script.addRound(n)

	# d = Sunny(Windy(Day("Koná se mistrovství světa v ledním hokeji")))
	# d.outage(Source.GAS) #there is a gas outage in this round
	# d.addBuildingModifier(Building.STADIUM, 100)  #increase stadium consumption because of a specific event
	# script.addRound(d)

	return script

if __name__ == "__main__":
	s = getScript()