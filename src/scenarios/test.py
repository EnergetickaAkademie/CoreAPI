from enak.Enak import *
import os

# Global debug flag from environment variable
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

building_consumptions = {
	# Default building consumptions (day, night) - same as demo scenario
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
	# Default source production ranges (min, max) - same as demo scenario
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
	
	# Allow ALL production sources from the start - everything unlocked for testing
	script.allowProduction(Source.COAL)
	script.allowProduction(Source.HYDRO)
	script.allowProduction(Source.HYDRO_STORAGE)
	script.allowProduction(Source.GAS)
	script.allowProduction(Source.NUCLEAR)
	script.allowProduction(Source.WIND)
	script.allowProduction(Source.PHOTOVOLTAIC)
	script.allowProduction(Source.BATTERY)
	
	# Test scenario: Multiple day/night cycles with different weather conditions
	# No slides - just gameplay rounds for testing
	
	# Round 1: Basic sunny day and calm night
	d = (Day()
		.comment("Test Day 1 - Sunny")
		.sunny()
		.build())
	script.addRound(d)
	
	n = (Night()
		.comment("Test Night 1 - Calm")
		.calm()
		.build())
	script.addRound(n)
	
	# Round 2: Windy day with good renewable generation
	d = (Day()
		.comment("Test Day 2 - Windy and Sunny")
		.sunny()
		.windy()
		.build())
	script.addRound(d)
	
	n = (Night()
		.comment("Test Night 2 - Windy")
		.windy()
		.build())
	script.addRound(n)
	
	# Round 3: Challenging weather - cloudy and calm (low renewables)
	d = (Day()
		.comment("Test Day 3 - Cloudy and Calm")
		.cloudy()
		.calm()
		.build())
	script.addRound(d)
	
	n = (Night()
		.comment("Test Night 3 - Cloudy and Calm")
		.cloudy()
		.calm()
		.build())
	script.addRound(n)
	
	# Round 4: Extreme weather - snowy and calm
	d = (Day()
		.comment("Test Day 4 - Snowy")
		.snowy()
		.calm()
		.build())
	script.addRound(d)
	
	n = (Night()
		.comment("Test Night 4 - Snowy")
		.snowy()
		.calm()
		.build())
	script.addRound(n)
	
	# Round 5: Test with power plant outage
	d = (Day()
		.comment("Test Day 5 - Gas Plant Outage")
		.sunny()
		.breezy()
		.outage(Source.GAS)
		.build())
	script.addRound(d)
	
	n = (Night()
		.comment("Test Night 5 - Gas Plant Outage")
		.breezy()
		.outage(Source.GAS)
		.build())
	script.addRound(n)
	
	# Round 6: Test with increased building consumption (stadium event)
	d = (Day()
		.comment("Test Day 6 - Stadium Event")
		.sunny()
		.windy()
		.addBuildingModifier(Building.STADIUM, 200)
		.addBuildingModifiers(CITY_CENTERS, 100)
		.build())
	script.addRound(d)
	
	n = (Night()
		.comment("Test Night 6 - Stadium Event")
		.windy()
		.addBuildingModifier(Building.STADIUM, 150)
		.addBuildingModifiers(CITY_CENTERS, 50)
		.build())
	script.addRound(n)
	
	# Round 7: Final test - perfect renewable conditions
	d = (Day()
		.comment("Test Day 7 - Perfect Renewables")
		.sunny()
		.windy()
		.build())
	script.addRound(d)
	
	n = (Night()
		.comment("Test Night 7 - Good Wind")
		.windy()
		.build())
	script.addRound(n)
	
	return script

if __name__ == "__main__":
	s = getScript()
