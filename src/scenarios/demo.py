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

source_productions = {
	#these numbers define the minimum and maximum
	Source.COAL: (250, 500),
	Source.HYDRO: (0, 100),
	Source.HYDRO_STORAGE: (-200, 200),
	Source.GAS: (0, 500),
	Source.NUCLEAR: (900, 1000),
	Source.WIND: (0, 100),
	Source.PHOTOVOLTAIC: (0, 100),
	Source.BATTERY: (-200, 200)
}

def getScript():
	script = Script(building_consumptions, source_productions)

	script.setPDF("prednaska.pdf")

	script.setVerbose(True)

	#FÁZE 1 - prezentace
	sr = SlideRange(1, 5)
	script.addRound(sr)

	#FÁZE 2 - umístění dvou uhelek a jedné budovy, jednoduché vyrovnání soustavy
	script.allowProduction(Source.COAL)

	d = (Day()
		.comment("Uhelky")
		.infoFile("/info/uhelky.md")
		.build())
	script.addRound(d)

	n = Night().setCoefficient(Source.HYDRO, 1.0).build()
	script.addRound(n)

	#FÁZE 3 - spotřeba města roste o 60MW ve dne, o 120MW v noci
	script.changeBuildingsConsumptions(CITY_CENTERS, (60, 120))
	script.allowProduction(Source.HYDRO)
	script.allowProduction(Source.HYDRO_STORAGE)

	d = Day().build()
	script.addRound(d)

	n = Night().build()
	script.addRound(n)

	#FÁZE 4 - jaderky, spotřeba roste o 100MW
	script.allowProduction(Source.NUCLEAR)
	script.changeBuildingsConsumptions(CITY_CENTERS, (100, 100))

	d = Day().build()
	script.addRound(d)

	n = Night().build()
	script.addRound(n)

	#FÁZE 5 - spotřeba města roste o 100MW, plynové elektrárny
	script.changeBuildingsConsumptions(CITY_CENTERS, (100, 100))
	script.allowProduction(Source.GAS)
	
	d = Day().build()
	script.addRound(d)

	n = Night().build()
	script.addRound(n)

	#FÁZE 6 - spotřeba města roste o 200 MW, nový typ OZE
	script.changeBuildingsConsumptions(CITY_CENTERS, (200, 200))
	script.allowProduction(Source.WIND)
	script.allowProduction(Source.PHOTOVOLTAIC)

	#normal calm day (average wind, average sun)
	d = Day().sunny().breezy().build()
	script.addRound(d)

	n = Night().breezy().build()
	script.addRound(n)

	#FÁZE 7 - scénáře

	# Je zima, zataženo, sněží a je bezvětří.
	d = (Day()
		.snowy()
		.calm()
		.cloudy()
		.build())
	script.addRound(d)

	n = (Night()
		.snowy()
		.calm()
		.cloudy()
		.build())
	script.addRound(n)

	# MS v hokeji, více lidí ve městě, porucha plynové elektrárny
	d = (Day()
		.sunny()
		.windy()
		.outage(Source.GAS)
		.addBuildingModifier(Building.STADIUM, 50)
		.addBuildingModifiers(CITY_CENTERS, 600)
		.comment("MS v hokeji")
		.build())
	script.addRound(d)

	n = (Night()
		.windy()
		.outage(Source.GAS)
		.addBuildingModifier(Building.STADIUM, 100)
		.addBuildingModifiers(CITY_CENTERS, 450)
		.build())
	script.addRound(n)
	
	return script

if __name__ == "__main__":
	s = getScript()