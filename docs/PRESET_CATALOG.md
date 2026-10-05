# Use-case and style presets

These presets are editorial starting points for Rec.709 SDR YouTube videos. Select one use case for the scene's baseline brightness and color, then select one aesthetic style. A style is composed over the use-case grade at its `defaults.intensity`; `natural` is an identity style, so it shows the use-case grade alone. Compare the listed styles on representative frames and moving footage before choosing. The values are not official YouTube targets or an optimal grade for every camera, person, or location.

## Use cases

`grade.curve` gives seven normalized output values for input luminance knots `[0, 0.05, 0.18, 0.4, 0.65, 0.85, 1]`. The curve, saturation, RGB gains, and shadow/highlight tints are global corrections. They do not detect faces or separate the subject from the background.

| ID | Intent | Manual subject range (IRE) | Manual background minus subject (IRE) | Default style | Suggested comparisons |
| --- | --- | ---: | ---: | --- | --- |
| `indoor_talk` | Natural room conversation | 45–70 | −25 to +15 | `natural` | Natural, Warm Documentary, Soft Film |
| `indoor_product` | Accurate product color and readable detail | 40–75 | −30 to +20 | `natural` | Natural, Clean Editorial, Soft Film |
| `indoor_lifestyle` | Mildly warm lived-in room | 40–70 | −30 to +20 | `warm_documentary` | Warm Documentary, Natural, Soft Film |
| `outdoor_daylight` | Sunlit detail and natural color | 45–75 | −30 to +30 | `clean_editorial` | Clean Editorial, Natural, Warm Documentary |
| `outdoor_overcast` | Soft daylight with gentle separation | 45–70 | −25 to +20 | `natural` | Natural, Clean Editorial, Warm Documentary |
| `outdoor_backlight` | Brighter subject with retained highlight detail | 40–70 | 0 to +40 | `natural` | Natural, Warm Documentary, Soft Film |
| `outdoor_night` | Dark atmosphere without crushed blacks | 20–55 | −25 to +25 | `natural` | Natural, Soft Film, Cinematic Teal |

The IRE ranges are **human viewing guidance**, not automatic face/background separation, guaranteed skin brightness, or a target to force on every shot. `background_delta_ire` means background IRE minus subject IRE; positive values allow a brighter background. Subject ranges may refer to an object in a product shot. Lighting direction, skin tone, material, exposure, and intended mood determine the appropriate level. Inspect waveform and representative frames, adjust exposure and white balance per shot, and use a local correction manually if a backlit subject needs one. At night, aggressive shadow lifting can reveal noise; preserve intentional darkness.

## Styles

| ID | Intent | Default intensity |
| --- | --- | ---: |
| `natural` | Identity reference; use-case grade only | 1.00 |
| `warm_documentary` | Restrained warmth and softer highlights | 0.65 |
| `clean_editorial` | Clear neutrals and crisp separation | 0.70 |
| `cinematic_teal` | Subtle cool shadows and warm highlights | 0.55 |
| `soft_film` | Soft contrast, small black lift, highlight rolloff | 0.65 |
| `monochrome` | Neutral black and white, blendable with intensity | 1.00 |

Style `grade.exposure_stops` defaults to zero for every entry. Style intensity ranges from zero (use-case baseline) to one (full style). `monochrome` has zero saturation at full intensity; intermediate intensity can retain color. Watch skin and neutrals when comparing tinted styles. These presets do not add grain, denoise footage, or perform local masking.
