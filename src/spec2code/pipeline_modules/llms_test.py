import re
from typing import Dict

class MockLLMResponse:
    """
    Mocks an LLM response with structured output following the expected format.
    """
    def __init__(self, model_name: str, response_text: str):
        self.model_name = model_name
        self.response_text = response_text
    
    def json(self) -> Dict[str, object]:
        return {
            "id": "mock-id-123",
            "choices": [{
                "finish_reason": "stop",
                "index": 0,
                "message": {
                    "content": self.response_text,
                    "role": "assistant"
                }
            }],
            "created": 1739368946,
            "model": self.model_name,
            "object": "chat.completion",
            "service_tier": "mock-tier",
            "system_fingerprint": "mock-fingerprint",
            "usage": {
                "completion_tokens": 100,
                "prompt_tokens": 150,
                "total_tokens": 250,
                "completion_tokens_details": {
                    "accepted_prediction_tokens": 10,
                    "audio_tokens": 0,
                    "reasoning_tokens": 5,
                    "rejected_prediction_tokens": 0
                },
                "prompt_tokens_details": {
                    "audio_tokens": 0,
                    "cached_tokens": 0
                }
            }
        }
    def duration_ms(self, prompt: str = ""):
        return 100
    
    def text(self) -> str:
        return self.response_text

class MockLLM:
    """
    A mock LLM model that can return different types of responses based on mode.
    """
    def __init__(self, mode: str = "default"):
        self.mode = mode

    def duration_ms(self, prompt: str):
        return 100
    
    def prompt(self, prompt: str, stream: bool = False, temperature: float = 0.7):
        def to_pipeline_format(code_block: str) -> str:
            text = code_block.strip()
            if text.startswith("```"):
                text = text.split("```", 1)[1]
                text = text.split("\n", 1)[1] if "\n" in text else ""
                text = text.rsplit("```", 1)[0]
            code = text.strip() + "\n"

            proto_match = re.search(
                r"(?m)^\s*([A-Za-z_][\w\s\*]*\s+[A-Za-z_]\w*\s*\([^\)]*\))\s*\{",
                code,
            )
            prototype = (proto_match.group(1).strip() + ";") if proto_match else "void generated_function(void);"

            header = "#ifndef GENERATED_H\n#define GENERATED_H\n\n" + prototype + "\n\n#endif\n"

            return f"BEGIN_C\n{code}END_C\nBEGIN_H\n{header}END_H"

        responses = {
            "default": """```c
/*@
    requires HEHEHE;
*/

int add(int* a, int* b) {
    return *a + *b;
}
```""",
            "main": """```c
void ShutdownAlgorithm_10ms(void)
{
    tU08 i;
    tB any_rs_active = false;

    for (i = 0u; i < 4u; ++i)
    {
        if (g_rs_state[i])
        {
            any_rs_active = true;
            break;
        }
    }

    for (i = 0u; i < 4u; ++i)
    {
        if (any_rs_active)
        {
            g_hysteresis_state[i] = g_rs_state[i];
        }
        else
        {
            g_hysteresis_state[i] = false;
        }
    }
}
```""",
            "shutdown_algorithm": """```c
void ShutdownAlgorithm_10ms(void)
{
    tU08 i;
    tB any_rs_active = false;

    for (i = 0u; i < 4u; ++i)
    {
        if (g_rs_state[i])
        {
            any_rs_active = true;
            break;
        }
    }

    for (i = 0u; i < 4u; ++i)
    {
        if (any_rs_active)
        {
            g_hysteresis_state[i] = g_rs_state[i];
        }
        else
        {
            g_hysteresis_state[i] = false;
        }
    }
}
```""",
            "formal_spec": """```c
int add(int* a, int* b) {
    return *a + *b;
}
```""",
            "sfld": """```c
void sfld_10ms(tB enabled_B)
{
    tS32S      oilLevelWarningTimer_S32s;   /* Timer for when to set error      */
    tBS        oldError_Bs;                 /* Check if error is set e.g. previous cycle */
    tBS        lowLevel_Bs;                 /* IO input from fluid level sensor */
    // static tBS oilLevelError_Bs;            /* Variable for error state to RTDB */
    
    /************************/
    /* Read input signals.  */
    /************************/
    lowLevel_Bs = rtdb_oilLevelLow_Bs;

    oilLevelWarningTimer_S32s = rtdb_warningTimer_S32s;
    Rteg_chkS32Input(&oilLevelWarningTimer_S32s, &oilLevelWarningTimer_S32s,(tS32) 0,(tS32) 0);

    /************************/
    /* Output algorithm.    */
    /************************/
    
    /* If first iteration make sure to get old status*/
    if (readLastWarn_B == FALSE)
    {
        oldError_Bs = rtdb_oldLevelError_Bs;
        if ((oldError_Bs.val_B == TRUE) && (GOOD_B(oldError_Bs.ss_U08) == TRUE))
        {
            /*Set timer to error level if error detected in cycle before */
            oilLevelWarningTimer_S32s.val_S32 = SFLD_TI_LIMIT_S32 - SFLD_TI_UPDATE_S32;
            readLastWarn_B = TRUE;
        }
        /* Old value checked and OK */
        else if (GOOD_B(oldError_Bs.ss_U08) == TRUE)
        {
            readLastWarn_B = TRUE;
        }
        else
        {
            /* nothing */
        }
    }

    /* Depending on low level detection iterate timer */
    if ((lowLevel_Bs.val_B == TRUE) && (GOOD_B(lowLevel_Bs.ss_U08) == TRUE))
    {
        oilLevelWarningTimer_S32s.val_S32 += SFLD_TI_UPDATE_S32;
    }
    if ((lowLevel_Bs.val_B == FALSE) && (GOOD_B(lowLevel_Bs.ss_U08) == TRUE))
    {
        oilLevelWarningTimer_S32s.val_S32 -= SFLD_TI_UPDATE_S32;

    }
    /* Saturate signal to valid limnits */
    oilLevelWarningTimer_S32s.val_S32 = SATURATE(oilLevelWarningTimer_S32s.val_S32, (tS16)0, SFLD_TI_LIMIT_S32);

    /* Set error true if timer reaches limit */
    if (oilLevelWarningTimer_S32s.val_S32 == SFLD_TI_LIMIT_S32)
    {
        oilLevelError_Bs.val_B = TRUE;
    }
    /* Set error false if timer set to zero  */
    else if (oilLevelWarningTimer_S32s.val_S32 == 0)
    {
        oilLevelError_Bs.val_B = FALSE;
    }
    else
    {
        /* Do Nothing */ 
    }

    /************************************/
    /* If enabled, write output data.   */
    /************************************/
    if (enabled_B == TRUE)
    {
        oilLevelError_Bs.ss_U08 = PENDINGOK_U08;
        rtdb_oilLevelWarn_Bs = oilLevelError_Bs;

        oilLevelWarningTimer_S32s.ss_U08 = PENDINGOK_U08;
        rtdb_warningTimer_S32s = oilLevelWarningTimer_S32s;

        /* Report result to DIMA */
        // Rteg_reportDiagTest(DIAG_TS_STEER_OIL_LEVEL_WARN_E,
        //     oilLevelError_Bs.val_B,
        //     TRUE);

        if (readLastWarn_B == TRUE)
        {
            rtdb_oldLevelError_Bs = oilLevelError_Bs;
        }
    }
  
}
```""",
            "sgmm": """```c
void sgmm_10ms(void)
{
    tB          electricMotorSpeedOk_B;
    tB          magneticValuesOk_B;
    tB          intermediateShaftOrCurrentGearOk_B;
    tB          startupTimeOk_B;

    /*-----------------------------------------------------------
     * Inline rtdbInput()
     *-----------------------------------------------------------*/
    lowMagneticValue_B               = rtdb_low_magnetic_value;
    highMagneticValue_B              = rtdb_high_magnetic_value;
    lowMagneticValueMeasurement_U08  = rtdb_low_magnetic_value_measurement.ss_U08;
    highMagneticValueMeasurement_U08 = rtdb_high_magnetic_value_measurement.ss_U08;
    currentGear_S08s                 = rtdb_current_gear;
    electricMotorMeasuredSpeed_F32s  = rtdb_electric_motor_measured_speed;
    intermediateShaftSpeed_F32s      = rtdb_intermediate_shaft_speed;

    /*-----------------------------------------------------------
     * Inline chckMvFbSs()
     *-----------------------------------------------------------*/
    if ((FLAWLESS_B(lowMagneticValueMeasurement_U08)  == TRUE) &&
        (FLAWLESS_B(highMagneticValueMeasurement_U08) == TRUE))
    {
        magneticValuesOk_B = TRUE;
    }
    else
    {
        magneticValuesOk_B = FALSE;
    }

    /*-----------------------------------------------------------
     * Inline chckEmOverSpeed()
     *-----------------------------------------------------------*/
    if ((TRUE == FLAWLESS_B(electricMotorMeasuredSpeed_F32s.ss_U08)) &&
        (electricMotorMeasuredSpeed_F32s.val_F32 <  MOTOROVERSPEEDLIMIT_F32) &&
        (electricMotorMeasuredSpeed_F32s.val_F32 > -MOTOROVERSPEEDLIMIT_F32))
    {
        electricMotorSpeedOk_B = TRUE;
    }
    else
    {
        electricMotorSpeedOk_B = FALSE;
    }

    /*-----------------------------------------------------------
     * Inline ChckSsInterShftAndCurrGear()
     *-----------------------------------------------------------*/
    if (TRUE == FLAWLESS_B(intermediateShaftSpeed_F32s.ss_U08))
    {
        /* Intermediate shaft is flawless */
        if ((intermediateShaftSpeed_F32s.val_F32 * GEARRATIO_F32) <= MOTOROVERSPEEDLIMIT_F32)
        {
            intermediateShaftOrCurrentGearOk_B = TRUE;
        }
        else
        {
            intermediateShaftOrCurrentGearOk_B = FALSE;
        }
    }
    else
    {
        /* Intermediate shaft not flawless; check current gear */
        if ((TRUE == FLAWLESS_B(currentGear_S08s.ss_U08)) &&
            (0 == currentGear_S08s.val_S08))
        {
            intermediateShaftOrCurrentGearOk_B = TRUE;
        }
        else
        {
            intermediateShaftOrCurrentGearOk_B = FALSE;
        }
    }

    /*-----------------------------------------------------------
     * Replicate the logic of the final if-else from sgmm_10ms,
     * inlining blockBoth() and noBlock().
     *-----------------------------------------------------------*/
    if (FALSE == magneticValuesOk_B)
    {
        /* blockBoth() inlined */
        rtdb_low_magnetic_value  = FALSE;
        rtdb_high_magnetic_value = FALSE;
    }
    else if (FALSE == electricMotorSpeedOk_B)
    {
        /* blockBoth() inlined */
        rtdb_low_magnetic_value  = FALSE;
        rtdb_high_magnetic_value = FALSE;
    }
    else if (FALSE == intermediateShaftOrCurrentGearOk_B)
    {
        /* blockBoth() inlined */
        rtdb_low_magnetic_value  = FALSE;
        rtdb_high_magnetic_value = FALSE;
    }
    else
    {
        /* noBlock() inlined */
        rtdb_low_magnetic_value  = lowMagneticValue_B;
        rtdb_high_magnetic_value = highMagneticValue_B;
    }
}
```""",  
            "brak": """```c
void Brak_10ms(void)
{
    tU08S       state;
    tBS         engineStart;
    tBS         blackout;
    tBS         req;
    tU08S       tmp;
    tU08S       remoteReq;
    tU08S       supplyStatus;

    tB          enabled;
    tB          active;

    tBS         truck;
    tBS         trailer;

    state = rtdb_state;
    validateInputU08(&state,
                     &state,
                     NORMAL_OPERATION,
                     NORMAL_OPERATION);
    
    engineStart = rtdb_engineStart;
    validateInputBool(&engineStart,&engineStart,FALSE,FALSE);

    blackout = rtdb_blackOut;
    validateInputBool(&blackout,&blackout,FALSE,FALSE);
    
    req = rtdb_req;
    validateInputBool(&req,&req,TRUE,TRUE);
    
    tmp = rtdb_remoteReq;
    validateInputU08(&tmp,
                     &remoteReq,
                     REMOTE_REQUEST_NONE,
                     REMOTE_REQUEST_NONE);

    supplyStatus = rtdb_supplyVoltageLevel;
    tmp = rtdb_supplyVoltageLevel;
    validateInputU08(&tmp,
                     &supplyStatus,
                     VOLTAGE_NORMAL,
                     VOLTAGE_NORMAL);

    if  (   
            (
                (state.val == NORMAL_OPERATION)
                ||
                (state.val == EMERGENCY_STOP_LIMITED)
            )
            &&
            (supplyStatus.val != VOLTAGE_LOW)
        )
    {
        enabled = TRUE;
        //@ assert Enabled: brakeLightEnabled(state, supplyStatus);
    }
    else
    {
        enabled = FALSE;
        //@ assert Disabled: !brakeLightEnabled(state, supplyStatus);
    }    
    
    if(remoteReq.val == REMOTE_REQUEST_OFF)
    {
        active = FALSE;
        //@ assert Inactive1: !brakeLightActive(remoteReq, supplyStatus, req, state, engineStart);
    }
    else if (
                (
                    (
                        (req.val == TRUE)
                        &&
                        (enabled == TRUE)
                    )
                    ||
                    (remoteReq.val == REMOTE_REQUEST_ON)
                )
                &&
                (engineStart.val == FALSE)
            )
    {
        active = TRUE;
        //@ assert Active: brakeLightActive(remoteReq, supplyStatus, req, state, engineStart);
    }
    else
    {
        active = FALSE;
        //@ assert Inactive2: !brakeLightActive(remoteReq, supplyStatus, req, state, engineStart);
    }

    truck.val        = FALSE;
    trailer.val      = FALSE;
    truck.ss_U08       = OK;
    trailer.ss_U08     = OK;
    
    if(active == TRUE)
    {
        truck.val    = TRUE;        

        if(blackout.val == FALSE)
        {
            trailer.val  = TRUE;
        }
    }

    rtdb_truck = truck;
    rtdb_trailer = trailer;
}
```""", 


        }
        response_text = to_pipeline_format(responses.get(self.mode, responses["default"]))
        return MockLLMResponse(model_name=f"mock-{self.mode}-model", response_text=response_text)


# Factory function to create mock models
def build_mock_models() -> Dict[str, MockLLM]:
    return {
        "test-llm": MockLLM("default"),
        "test-llm-fs": MockLLM("formal_spec"),
        "test-llm-main": MockLLM("shutdown_algorithm"),
        "test-llm-shutdown": MockLLM("shutdown_algorithm"),
        "test-llm-brak": MockLLM("brak"),
        "test-llm-sgmm": MockLLM("sgmm"),
        "test-llm-sfld": MockLLM("sfld"),
    }
