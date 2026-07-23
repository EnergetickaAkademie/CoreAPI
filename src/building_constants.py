from enak import Enak

BUILDING_NAME = {
	Enak.Building.CITY_CENTER:				"Centrum města",
	Enak.Building.CITY_CENTER_A:			"Centrum města A",
	Enak.Building.CITY_CENTER_B:			"Centrum města B",
	Enak.Building.CITY_CENTER_C:			"Centrum města C",
	Enak.Building.CITY_CENTER_D:			"Centrum města D",
	Enak.Building.CITY_CENTER_E:			"Centrum města E",
	Enak.Building.CITY_CENTER_F:			"Centrum města F",
	Enak.Building.FACTORY:					"Továrna",
	Enak.Building.STADIUM:					"Stadion",
	Enak.Building.HOSPITAL:					"Nemocnice",
	Enak.Building.UNIVERSITY:				"Univerzita",
	Enak.Building.AIRPORT:					"Letiště",
	Enak.Building.SHOPPING_MALL:			"Obchodní centrum",
	Enak.Building.TECHNOLOGY_CENTER:		"Technologické centrum",
	Enak.Building.FARM:						"Farma",
	Enak.Building.LIVING_QUARTER_SMALL:		"Menší obytná čtvrť",
	Enak.Building.LIVING_QUARTER_LARGE:		"Větší obytná čtvrť",
	Enak.Building.SCHOOL:					"Škola",
}

def get_building_name(building: Enak.Building):
	return BUILDING_NAME[building]