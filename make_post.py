import os
import re
import argparse
import time
import requests
import asyncio
from EdgeGPT import Chatbot
# import yaml
from yaml import load, dump, Loader
import json
import io
import warnings
import shutil
from PIL import Image
from stability_sdk import client
import stability_sdk.interfaces.gooseai.generation.generation_pb2 as generation

pattern = r"\[\^\d\^\]"
# Our Host URL should not be prepended with "https" nor should it have a trailing slash.
os.environ['STABILITY_HOST'] = 'grpc.stability.ai:443'
os.environ["STABILITY_KEY"] = os.getenv("STABILITY_KEY")

def generate_image(cfg:dict)-> None:
    prompt = cfg['imageArgs']['prompt']
    stability_api = client.StabilityInference(
        key=os.environ['STABILITY_KEY'], # API Key reference.
        verbose=True, # Print debug messages.
        engine="stable-diffusion-v1-5", # Set the engine to use for generation. 
        # Available engines: stable-diffusion-v1 stable-diffusion-v1-5 stable-diffusion-512-v2-0 stable-diffusion-768-v2-0 
        # stable-diffusion-512-v2-1 stable-diffusion-768-v2-1 stable-inpainting-v1-0 stable-inpainting-512-v2-0
    )
    answers = stability_api.generate(
        prompt=prompt
    )
    for resp in answers:
        for artifact in resp.artifacts:
            if artifact.finish_reason == generation.FILTER:
                warnings.warn(
                    "Your request activated the API's safety filters and could not be processed."
                    "Please modify the prompt and try again.")
            if artifact.type == generation.ARTIFACT_IMAGE:
                img = Image.open(io.BytesIO(artifact.binary))
                # images
                image_root = "images" + "/" + str(artifact.seed)+ ".png"
                img.save(image_root) # Save our generated images with their seed number as the filename.
                return image_root

def generate_frontmatter(cfg: dict)-> None:
    # open output file
    output_file = cfg['outputFile']
    with open(output_file, 'w') as f:
        # write frontmatter
        f.write('---\n')
        # get frontmatter
        frontmatter = cfg['frontMatter']
        for key, value in frontmatter.items():
            f.write(f'{key}: {value}\n')
        f.write('---\n')
        # write body
    pass

def use_programming_language(cfg: dict, section_text: str, language: str = None)-> None:
    # get programming language
    programming_language = language or cfg['programmingLanguage']
    # use regex to find plain ``` and replace with ```programming_language
    type_start_line = None
    type_end_line = None
    # replace with code blocks with programming language
    # split lines by \n
    modified_lines = []
    lines = section_text.split('\n')
    for i, line in enumerate(lines):
        if line == '```':
            if type_start_line is None:
                type_start_line = i
                # append modified line
                modified_lines.append(f'```{programming_language}')
            else:
                # odd number of ``` so we are ending a code block
                type_start_line = None
                # append modified line
                modified_lines.append('```')
        else:
            # adjust line if type_start_line is not None
            # remove ` at the beginning of the line and the end of the line
            if type_start_line is not None:
                # check for ` character at the beginning of the line
                if line.strip() != '':
                    if line[0] == '`':
                        line = line[1:]
                    # check for ` character at the end of the line
                    if line[-1] == '`':
                        line = line[:-1]
            modified_lines.append(line)

    return "\n".join(modified_lines)

def try_chatgpt_response(text: str):
    attempts = 0
    while attempts < 3:
        try:
            resp = api.send_message(text)
            return resp
        except Exception as e:
            attempts += 1
            time.sleep(3)
            if attempts == 3:
                raise e
    raise Exception("Failed to get response from ChatGPT")


async def handlePrompt(bot: Chatbot, prompt: str):
    resp = await bot.ask(prompt)
    # get resp item.messages
    # filter for bot responses
    # find text equal to prompt, then grab the next message then return the text of that message
    for i, message in enumerate(resp.get("item", {}).get("messages", [])):
        if message.get("text", "") == prompt:
            raw_resp = resp.get("item", {}).get("messages", [])
            try:
                raw_message = raw_resp[i+1].get("text", "")
            except:
                # grab latest message
                raw_message = raw_resp[-1].get("text", "")
                if raw_message == "":
                    return ""
                # no message after prompt
                return ""
            break
    # clean message
    clean_message = re.sub(pattern, "", raw_message)
    return clean_message
    

async def generate_body(cfg: dict)-> None:
    # read CHATGPT_TOKEN from os
    bot = Chatbot(cookiePath="cookies.json")
    output_file = cfg['outputFile']
    sections = cfg['sections']
    # send seed prompt if available
    if 'seedPrompt' in cfg:
        seed_prompt = cfg['seedPrompt']
        resp = await bot.ask(prompt=seed_prompt)
        time.sleep(3)
    with open(output_file, 'a', encoding="utf-8", errors="replace") as f:
        for section in sections:
            # check if str or dict
            if isinstance(section, str):
                resp = await handlePrompt(bot, section)
                print(resp)
                clean_message = use_programming_language(cfg, resp)
            else:
                # assume dict
                # type and src from dict
                input_type = section['type']
                src = section['src']
                language = section.get('language', None)
                if input_type == 'file':
                    # read src from file
                    with open(src, 'r') as src_file:
                        src_text = src_file.read()
                    # check for lines argument
                    if 'lines' in section:
                        lines = section['lines']
                        # make sure lines is a list
                        if isinstance(lines, list):
                            # get lines from src_text
                            src_lines = src_text.split('\n')
                            src_text = "\n".join(src_lines[lines[0]:lines[1]])
                    resp = await handlePrompt(bot, section)
                    clean_message = resp['message']
                    # write original text
                    programming_language = language or cfg['programmingLanguage'] 
                    f.write(f"```{programming_language} \n {src_text} \n ```\n")
                    f.write('\n')
                if input_type == 'url':
                    # load from url
                    src_text = requests.get(src).text
                    if 'lines' in section:
                        lines = section['lines']
                        # make sure lines is a list
                        if isinstance(lines, list):
                            # get lines from src_text
                            src_lines = src_text.split('\n')
                            src_text = "\n".join(src_lines[lines[0]:lines[1]])
                    # check if file should be saved to file
                    if 'saveFile' in section:
                        save_file = section['saveFile']
                        if save_file:
                            # save file to src
                            with open(src, 'w') as src_file:
                                src_file.write(src_text)
                    resp = await handlePrompt(bot, section)
                    clean_message = resp['message']
                    # write original text
                    programming_language = language or cfg['programmingLanguage']
                    f.write(f"```{programming_language} \n {src_text} \n ```\n")
                    f.write('\n')
                if input_type == 'raw':
                    clean_message = src
            f.write(clean_message)
            f.write('\n')
            time.sleep(5)
        # output references
        try:
            references = cfg['references']
            if references:
                f.write('\n')
                f.write('## References\n')
                for reference in references:
                    if 'title' in reference and 'url' in reference:
                        f.write(f"- [{reference['title']}]({reference['url']})\n")
                    else:
                        f.write(f"- {reference}\n")
        except Exception as e:
            print(e)
            pass
    await bot.close()


async def main(args):
    image_root = ""
    # valid files exist
    # argparse for file eventually
    with open(args.file, 'r') as f:
        cfg = load(f, Loader=Loader)
    # if file exists skip
    # if not run these functions
    if os.path.exists(cfg['outputFile']):
        print('file exists')
        exit(0)
    # if genImage is true, then makeImage
    if cfg['imageArgs']:
        image_path = generate_image(cfg)
        pass
    
    astro_image_folder = "/imgs/2023"
    # grab basename from image_path
    image_basename = os.path.basename(image_path)
    imgSrc = f"{astro_image_folder}/{image_basename}"
    #
    cfg["frontMatter"]["imgSrc"] = imgSrc
    generate_frontmatter(cfg)
    await generate_body(cfg)

    ## cp file to ../astro-tech-blog/${directory}
    try:
        if cfg["postOutput"]:
            # check for postOutput.folder
            # check for postOutput.imgFolder
            # mv cfg['outputFile'] to ../astro-tech-blog/${postOutput.folder}
            post_output_folder = cfg['postOutput']['folder']
            post_output_img_folder = cfg['postOutput']['imgFolder']
            if post_output_folder:
                # copy file to ../astro-tech-blog/${postOutput.folder}
                shutil.copy(cfg['outputFile'], post_output_folder)
                # copy image to ../astro-tech-blog/${postOutput.imgFolder}
            if post_output_img_folder:
                shutil.copy(image_path, post_output_img_folder)
    except Exception as e:
        print(e)
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=str, default='posts/scrapping_with_pandas_and_bs4.yml')
    args = parser.parse_args()
    asyncio.run(main(args))
