from testbook import testbook
import os

@testbook(
    "docs/notebook_tutorial/ocr.ipynb", execute=False
)
def test_wrap_MT_inference_pipeline(tb):
    # if we just want to run through the notebook
    tb.execute_cell("ocr_reader")
    tb.execute_cell("ocr_char_processor")
    tb.execute_cell("ocr_token_processor")
    tb.execute_cell("get_image")
    tb.execute_cell("pipeline")
    tb.execute_cell("recognize_char")
    recognized_chars = ['T', 'e', 'x', 't', 'M', 'e', 's', 's', 'a', 'g', 'e', 'T', 'o', 'd', 'a', 'y', '1', '5', ':', '4', '6', 'I', 't', 's', 'E', 'm', 'm', 'a', '.', '|', 't', 'r', 'i', 'e', 'd', 't', 'o', 'c', 'a', 'l', 'l', 'y', 'o', 'u', 'b', 'u', 't', 's', 'i', 'g', 'n', 'a', 'l', 'b', 'a', 'd', '.', '|', 'b', 'e', 'e', 'n', 't', 'a', 'k', 'e', 'n', 't', 'o', 'h', 'o', 's', 'p', 'i', 't', 'a', 'l', 'a', 'f', 't', 'e', 'r', 'h', 'a', 'v', 'i', 'n', 'g', 'a', 'f', 'a', 'l', 'l', 't', 'h', 'i', 's', 'm', 'o', 'r', 'n', 'i', 'n', 'g', '.', 'I', 'f', 'p', 'o', 's', 's', 'i', 'b', 'l', 'e', 'c', 'a', 'n', 'y', 'o', 'u', 'd', 'o', 'm', 'e', 'a', 'q', 'u', 'i', 'c', 'k', 'f', 'a', 'v', 'o', 'u', 'r', 'a', 'n', 'd', 't', 'e', 'x', 't', 'm', 'e', 'x']
    recognized_chars_output = "Recognized characters: \n" + " " + str(recognized_chars)
    assert tb.cell_output_text("recognize_char") == recognized_chars_output
    
    tb.execute_cell("recognize_token")
    recognized_tokens = ['Text', 'Message', 'Today', '15:46', 'Its', 'Emma.', '|', 'tried', 'to', 'call', 'you', 'but', 'signal', 'bad.', '|', 'been', 'taken', 'to', 'hospital', 'after', 'having', 'a', 'fall', 'this', 'morning.', 'If', 'possible', 'can', 'you', 'do', 'me', 'a', 'quick', 'favour', 'and', 'text', 'me', 'x']
    recognize_token_output = "Recognized tokens: \n" + " " + str(recognized_tokens)
    assert tb.cell_output_text("recognize_token") == recognize_token_output
    
