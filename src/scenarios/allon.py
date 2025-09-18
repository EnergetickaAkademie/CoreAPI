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
	sr = Slide("demo/outputname-01.png")

	script.addRound(sr)

	script.allowProduction(Source.COAL)
	script.allowProduction(Source.HYDRO)
	script.allowProduction(Source.HYDRO_STORAGE)
	script.allowProduction(Source.NUCLEAR)
	script.allowProduction(Source.GAS)
	script.allowProduction(Source.WIND)
	script.allowProduction(Source.PHOTOVOLTAIC)
	script.allowProduction(Source.BATTERY)

	sl = Slide("normal/39.svg")
	script.addRound(sl)

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

	return script

if __name__ == "__main__":
	s = getScript()