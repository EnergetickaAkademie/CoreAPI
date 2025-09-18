from enak.Enak import *
from random import randint

building_consumptions = {
	Building.CITY_CENTER_A: (randint(550, 620), randint(350, 400)),
	Building.CITY_CENTER_B: (randint(550, 620), randint(350, 400)),
	Building.CITY_CENTER_C: (randint(550, 620), randint(350, 400)),
	Building.CITY_CENTER_D: (randint(550, 620), randint(350, 400)),
	Building.CITY_CENTER_E: (randint(550, 620), randint(350, 400)),
	Building.CITY_CENTER_F: (randint(550, 620), randint(350, 400)),
	
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
	Source.HYDRO: (0, 200),
	Source.HYDRO_STORAGE: (-200, 200),
	Source.GAS: (0, 500),
	Source.NUCLEAR: (900, 1000),
	Source.WIND: (0, 100),
	Source.PHOTOVOLTAIC: (0, 100),
	Source.BATTERY: (-200, 200)
}

def getScript():
	script = Script(building_consumptions, source_productions)

	#script.setVerbose(True)

	#FÁZE 1 - prezentace
	sr = SlideRange(["demo/outputname-01.png",
					#"demo/outputname-02.png",
					"normal/03.svg",
					"normal/04.svg",
					"normal/05.svg",
					"normal/06.svg",
					"normal/07.svg",
					"normal/08.svg"])

	script.addRound(sr)

	#FÁZE 2 - umístění dvou uhelek a jedné budovy, jednoduché vyrovnání soustavy
	script.allowProduction(Source.COAL)

	d = (Day()
		.comment("Uhelky")
		.build())
	script.addRound(d)

	s = Slide("normal/12.svg")
	script.addRound(s)

	n = Night().build()
	script.addRound(n)

	sl = Slide("normal/14.svg")
	script.addRound(sl)

	#FÁZE 3 - spotřeba města roste o 60MW ve dne, o 120MW v noci
	script.changeBuildingsConsumptions(CITY_CENTERS, (120, 60))
	script.allowProduction(Source.HYDRO)
	script.allowProduction(Source.HYDRO_STORAGE)

	d = Day().build()
	script.addRound(d)

	sl = Slide("normal/17.svg")
	script.addRound(sl)

	n = Night().build()
	script.addRound(n)

	sl = Slide("normal/19.svg")
	script.addRound(sl)

	#FÁZE 4 - JADERKY
	script.allowProduction(Source.NUCLEAR)
	script.changeBuildingsConsumptions(CITY_CENTERS, (150, 150))

	d = Day().build()
	script.addRound(d)

	sl = Slide("normal/22.svg")
	script.addRound(sl)

	n = Night().build()
	script.addRound(n)

	sl = Slide("normal/24.svg")
	script.addRound(sl)

	#FÁZE 5 - spotřeba města roste o 100MW, plynové elektrárny
	script.changeBuildingsConsumptions(CITY_CENTERS, (100, 100))
	script.allowProduction(Source.GAS)
	
	d = Day().build()
	script.addRound(d)

	sl = Slide("normal/27.svg")
	script.addRound(sl)

	n = Night().build()
	script.addRound(n)

	sr = SlideRange(["normal/29.svg",
					"normal/30.svg",
					"normal/31.svg"])

	script.addRound(sr)

	#FÁZE 6 - spotřeba města roste o 200 MW, nový typ OZE
	script.changeBuildingsConsumptions(CITY_CENTERS, (200, 200))
	script.allowProduction(Source.WIND)
	script.allowProduction(Source.PHOTOVOLTAIC)
	script.allowProduction(Source.BATTERY)

	d = (Day()
		.sunny()
		.windy()
		.build())

	script.addRound(d)

	sl = Slide("normal/34.svg")
	script.addRound(sl)

	n = (Night()
		.windy()
		.build())

	script.addRound(n)

	sl = Slide("normal/39.svg")
	script.addRound(sl)

	#scénář 2: MS v hokeji, porucha plyn elektrárny
	# spotřeba vyrostla o 600MW ve dne v noci o 450MW

	d = (Day()
		.comment("MS v hokeji, porucha plyn elektrárny")
		.addBuildingModifiers(CITY_CENTERS, 600)
		.outage(Source.GAS)
		.partly_cloudy()
		.windy()
		.build())

	script.addRound(d)

	sl = Slide("normal/34.svg")
	script.addRound(sl)

	n = (Night()
		.addBuildingModifiers(CITY_CENTERS, 450)
		.outage(Source.GAS)
		.breezy()
		.build())

	script.addRound(n)

	sr = SlideRange(["normal/36.svg",
					"normal/37.svg",
					"normal/38.svg"])

	script.addRound(sr)

	return script

if __name__ == "__main__":
	s = getScript()