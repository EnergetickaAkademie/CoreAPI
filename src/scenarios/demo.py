from enak.Enak import *
import os

# Global debug flag from environment variable
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

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

	script.setVerbose(DEBUG)

	#FÁZE 1 - prezentace
	sr = SlideRange(["demo/outputname-01.png", "demo/outputname-02.png", "demo/outputname-03.png"])
	script.addRound(sr)

	sl = Slide("demo/outputname-04.png")
	script.addRound(sl)

	#FÁZE 2 - umístění dvou uhelek a jedné budovy, jednoduché vyrovnání soustavy
	script.allowProduction(Source.COAL)

	d = (Day()
		.comment("Uhelky")
		.build())
	script.addRound(d)

	n = Night().build()
	script.addRound(n)

	sl = Slide("demo/outputname-05.png")
	script.addRound(sl)

	#FÁZE 3 - spotřeba města roste o 60MW ve dne, o 120MW v noci
	script.changeBuildingsConsumptions(CITY_CENTERS, (60, 120))
	script.allowProduction(Source.HYDRO)
	script.allowProduction(Source.HYDRO_STORAGE)
	script.allowProduction(Source.BATTERY)

	d = Day().build()
	script.addRound(d)

	n = Night().build()
	script.addRound(n)

	sl = Slide("demo/outputname-06.png")
	script.addRound(sl)

	#FÁZE 4 - jaderky, spotřeba roste o 100MW
	script.allowProduction(Source.NUCLEAR)
	script.changeBuildingsConsumptions(CITY_CENTERS, (100, 100))

	d = Day().build()
	script.addRound(d)

	n = Night().build()
	script.addRound(n)

	sl = Slide("demo/outputname-07.png")
	script.addRound(sl)

	#FÁZE 5 - spotřeba města roste o 100MW, plynové elektrárny
	script.changeBuildingsConsumptions(CITY_CENTERS, (100, 100))
	script.allowProduction(Source.GAS)
	
	d = Day().build()
	script.addRound(d)

	n = Night().build()
	script.addRound(n)

	sl = Slide("demo/outputname-08.png")
	script.addRound(sl)

	#FÁZE 6 - spotřeba města roste o 200 MW, nový typ OZE
	script.changeBuildingsConsumptions(CITY_CENTERS, (200, 200))
	script.allowProduction(Source.WIND)
	script.allowProduction(Source.PHOTOVOLTAIC)

	#normal calm day (average wind, average sun)
	d = Day().sunny().breezy().build()
	script.addRound(d)

	n = Night().breezy().build()
	script.addRound(n)

	sl = Slide("demo/outputname-09.png")
	script.addRound(sl)
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

	sl = Slide("demo/outputname-10.png")
	script.addRound(sl)

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