"""
Weather Message Handler for WebControl

This module handles the generation of weather-related messages for powerplants
based on round types (DAY/NIGHT) and weather conditions. It implements a
last-effect-wins system where later weather conditions override earlier ones
for the same powerplant type.
"""

from typing import List, Dict, Any, Set, Optional
from enak import Source


class WeatherMessageHandler:
    """
    Handles weather message generation for powerplants.
    
    The system works as follows:
    1. Start with baseline round type effects (e.g., NIGHT sets solar off, wind off)
    2. Apply weather conditions in sequence, with later conditions overriding earlier ones
    3. Filter effects based on enabled powerplant types, but preserve "not producing" messages
    """
    
    def __init__(self, display_translations: Dict[str, Any]):
        """
        Initialize the weather message handler.
        
        Args:
            display_translations: Dictionary containing display data for weather conditions and round types
        """
        self.display_translations = display_translations
    
    def generate_weather_display_data(
        self,
        round_type: Any,
        weather_conditions: List[Any],
        script: Any
    ) -> Dict[str, Any]:
        """
        Generate complete display data including weather messages for the current round.
        
        Args:
            round_type: The current round type (DAY/NIGHT/etc.)
            weather_conditions: List of weather conditions affecting this round
            script: Game script containing production coefficients
            
        Returns:
            Dictionary containing display data with properly filtered and ordered effects
        """
        # Start with base round type data
        round_key = round_type.name
        display_data = self.display_translations[round_key].copy()
        
        # Apply specific weather data if available
        if weather_conditions:
            # Process all weather conditions to build combined display data
            # Later conditions can override earlier ones if they have non-None values
            
            # First, use the first weather condition for primary display (icon, name, background, etc.)
            primary_weather = weather_conditions[0]
            primary_weather_key = primary_weather.name.upper() if hasattr(primary_weather, 'name') else str(primary_weather).upper()
            
            if primary_weather_key in self.display_translations:
                primary_weather_data = self.display_translations[primary_weather_key].copy()
                
                # Override base data with primary weather data (only if values exist)
                for key, value in primary_weather_data.items():
                    if value is not None and key != 'effects':  # Don't override effects yet
                        display_data[key] = value
                
                # Set the weather name from the primary condition
                display_data['name'] = primary_weather_data.get('name', display_data['name'])
            
            # Then process all weather conditions to override specific values (like wind_speed, temperature)
            # This allows later conditions to override values from earlier conditions or base round type
            for weather in weather_conditions:
                weather_key = weather.name.upper() if hasattr(weather, 'name') else str(weather).upper()
                
                if weather_key in self.display_translations:
                    weather_data = self.display_translations[weather_key]
                    
                    # Override specific display properties if they have non-None values
                    for key in ['wind_speed', 'temperature']:
                        if weather_data.get(key) is not None:
                            display_data[key] = weather_data[key]
        
        # Generate weather effects with proper filtering
        display_data['effects'] = self._generate_weather_effects(
            display_data, weather_conditions, script
        )
        
        return display_data
    
    def _generate_weather_effects(
        self,
        base_display_data: Dict[str, Any],
        weather_conditions: List[Any],
        script: Any
    ) -> List[Dict[str, Any]]:
        """
        Generate weather effects with last-effect-wins logic and proper filtering.
        
        Args:
            base_display_data: Base display data containing baseline effects
            weather_conditions: List of weather conditions to process
            script: Game script containing production coefficients
            
        Returns:
            List of effect dictionaries, properly filtered and ordered
        """
        # Get enabled powerplant types (sources with coefficient > 0)
        enabled_sources = self._get_enabled_sources(script)
        
        # Build effect mapping with last-effect-wins logic
        effect_by_type = {}
        
        # 1. Start with baseline round-type effects
        self._apply_effects(
            base_display_data.get('effects', []),
            effect_by_type,
            enabled_sources
        )
        
        # 2. Apply weather conditions in order (later ones override earlier ones)
        for weather in weather_conditions:
            weather_key = weather.name.upper() if hasattr(weather, 'name') else str(weather).upper()
            if weather_key not in self.display_translations:
                continue
            
            weather_data = self.display_translations[weather_key]
            self._apply_effects(
                weather_data.get('effects', []),
                effect_by_type,
                enabled_sources
            )
        
        # 3. Convert back to sorted list
        return self._sort_effects(effect_by_type)
    
    def _get_enabled_sources(self, script_instance):
        """Get set of registered/unlocked source types in the game."""
        enabled_sources = set()
        
        if script_instance:
            registered_sources = script_instance.getRegisteredSources()
            
            for source in registered_sources:
                enabled_sources.add(source.value)
        
        return enabled_sources
    
    def _apply_effects(
        self,
        effects: List[Dict[str, Any]],
        effect_by_type: Dict,
        enabled_sources: Set[int]
    ) -> None:
        """
        Apply effects to the effect mapping with proper filtering.
        
        Args:
            effects: List of effects to apply
            effect_by_type: Dictionary mapping effect types to effects (modified in place)
            enabled_sources: Set of enabled source values
        """
        for effect in effects:
            effect_type = effect.get('type')
            
            if effect_type is None:
                # Non-typed effects (rare) - use text as pseudo key
                pseudo_key = f"text::{effect.get('text', '')}"
                effect_by_type[pseudo_key] = effect
            else:
                # Typed effects for powerplants
                if self._should_include_effect(effect, effect_type, enabled_sources):
                    effect_by_type[effect_type] = effect
    
    def _should_include_effect(
        self,
        effect: Dict[str, Any],
        effect_type: int,
        enabled_sources: Set[int]
    ) -> bool:
        """
        Determine if an effect should be included based on filtering rules.
        
        Only show effects for powerplant types that are currently enabled in the game.
        If no powerplant types are enabled yet, show no effects.
        
        Args:
            effect: The effect dictionary
            effect_type: The powerplant type (Source value)
            enabled_sources: Set of enabled source values
            
        Returns:
            True if the effect should be included
        """
        # Only show effects for powerplant types that are enabled in the game
        return effect_type in enabled_sources
    
    def _sort_effects(self, effect_by_type: Dict) -> List[Dict[str, Any]]:
        """
        Sort effects for deterministic output.
        
        Args:
            effect_by_type: Dictionary mapping effect types to effects
            
        Returns:
            Sorted list of effects
        """
        if not effect_by_type:
            return []
        
        # Separate typed effects (powerplants) from pseudo effects (text-based)
        typed_effects = [e for k, e in effect_by_type.items() if not isinstance(k, str)]
        pseudo_effects = [e for k, e in effect_by_type.items() if isinstance(k, str)]
        
        # Sort typed effects by powerplant type
        typed_effects.sort(key=lambda e: e.get('type', 0))
        
        return typed_effects + pseudo_effects
