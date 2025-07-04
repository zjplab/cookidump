#!/usr/bin/python3

# cookidump
# Original GitHub project:
# https://github.com/auino/cookidump

import os
import io
import re
import time
import json
import pathlib
import argparse
import platform
from bs4 import BeautifulSoup
from selenium import webdriver
from urllib.parse import urlparse
from urllib.request import urlretrieve
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains

PAGELOAD_TO = 3
SCROLL_TO = 1
MAX_SCROLL_RETRIES = 5

def startBrowser(chrome_driver_path):
    """Starts browser with predefined parameters"""
    chrome_options = Options()
    if "GOOGLE_CHROME_PATH" in os.environ:
        chrome_options.binary_location = os.getenv('GOOGLE_CHROME_PATH')
    #chrome_options.add_argument('--headless')
    chrome_service = Service(chrome_driver_path)
    driver = webdriver.Chrome(service=chrome_service, options=chrome_options)
    return driver

def listToFile(browser, baseDir):
    """Gets html from search list and saves in html file"""
    filename = '{}index.html'.format(baseDir)
    # creating directories, if needed
    path = pathlib.Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    # getting web page source
    #html = browser.page_source
    html = browser.execute_script("return document.documentElement.outerHTML")
    # saving the page
    with io.open(filename, 'w', encoding='utf-8') as f: f.write(html)

def imgToFile(outputdir, recipeID, img_url):
    img_path = '{}images/{}.jpg'.format(outputdir, recipeID)
    path = pathlib.Path(img_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(img_url, img_path)
    return '../images/{}.jpg'.format(recipeID)

def recipeToFile(browser, filename):
    """Gets html of the recipe and saves in html file"""
    # creating directories, if needed
    path = pathlib.Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    # getting web page source
    html = browser.page_source
    # saving the page
    with io.open(filename, 'w', encoding='utf-8') as f: f.write(html)

def recipeToJSON(browser, recipeID):
    html = browser.page_source
    soup = BeautifulSoup(html, 'html.parser')

    recipe = {}
    recipe['id'] = recipeID
    recipe['language'] = soup.select_one('html').attrs['lang']
    recipe['title'] = soup.select_one(".recipe-card__title").text
    recipe['rating_count'] = re.sub(r'\D', '', soup.select_one(".core-rating__label").text, flags=re.IGNORECASE)
    recipe['rating_score'] = soup.select_one(".core-rating__counter").text
    recipe['tm-versions'] = [v.text.replace('\n','').strip().lower() for v in soup.select(".recipe-card__tm-version core-badge")]
    recipe.update({ l.text : l.next_sibling.strip() for l in soup.select("core-feature-icons label span") })
    recipe['ingredients'] = [re.sub(' +', ' ', li.text).replace('\n','').strip() for li in soup.select("#ingredients li")]
    recipe['nutritions'] = {}
    for item in list(zip(soup.select(".nutritions dl")[0].find_all("dt"), soup.select(".nutritions dl")[0].find_all("dd"))):
        dt, dl = item
        recipe['nutritions'].update({ dt.string.replace('\n','').strip().lower(): re.sub(r'\s{2,}', ' ', dl.string.replace('\n','').strip().lower()) })
    recipe['steps'] = [re.sub(' +', ' ', li.text).replace('\n','').strip() for li in soup.select("#preparation-steps li")]
    recipe['tags'] = [a.text.replace('#','').replace('\n','').strip().lower() for a in soup.select(".core-tags-wrapper__tags-container a")]

    return recipe

def run(webdriverfile, outputdir, separate_json):
    """Scraps all recipes and stores them in html"""
    print('[CD] Welcome to cookidump, starting things off...')
    # fixing the outputdir parameter, if needed
    if outputdir[-1:][0] != '/':
        outputdir += '/'

    # ------------------------------------------------------------------
    # HARDCODED TARGET URL (Chinese Cookidoo search page)
    # ------------------------------------------------------------------
    searchURL = 'https://cookidoo.com.cn/search/zh-Hans-CN?languages=zh'

    # derive root domain & language code for later use (logout, etc.)
    parsed_url = urlparse(searchURL)
    rootURL = f"{parsed_url.scheme}://{parsed_url.netloc}"
    language_code = 'zh-Hans-CN'

    brw = startBrowser(webdriverfile)

    # open search page directly – user can log in from there
    brw.get(searchURL)
    time.sleep(PAGELOAD_TO)
    input('[CD] 请登录 Cookidoo 账户后，在终端输入 y 继续 (login then type y): ')
    # recipes base url (supports optional language code suffix)
    rbURL = f"{rootURL}/search/"
    if language_code:
        rbURL += f"{language_code}/"
    brw.get(rbURL)
    time.sleep(PAGELOAD_TO)
    # possible filters done here
    input('[CD] 如需筛选，请在浏览器页面设置后，在终端输入 y 继续 (set filters if desired then type y): ')
    # asking for additional details for output organization
    custom_output_dir = input("[CD] enter the directory name to store the results (ex. vegeratian): ")
    if custom_output_dir : outputdir += '{}/'.format(custom_output_dir)
    # proceeding
    print('[CD] Proceeding with scraping')
    # removing the name
    brw.execute_script("var element = arguments[0];element.parentNode.removeChild(element);", brw.find_element(By.TAG_NAME, 'core-user-profile'))
    # clicking on cookie accept
    try: brw.find_element(By.CLASS_NAME, 'accept-cookie-container').click()
    except: pass
    # showing all recipes
    # Try to retrieve the total amount of recipes reported by the site. If the markup
    # changes (again) and we cannot find it, just set a very large number so that the
    # scrolling logic relies on the "no-new-elements" heuristic instead.
    import re as _re  # local import to avoid issues if re not imported globally
    try:
        stats_text = brw.find_element(By.CLASS_NAME, 'items-start').text
        elements_match = _re.search(r'\d+', stats_text.replace(',', ''))
        elementsToBeFound = int(elements_match.group()) if elements_match else 10**9
    except Exception:
        elementsToBeFound = 10**9  # fallback when result counter cannot be located

    previousElements = 0
    retry_counter = 0

    while True:
        currentElements = len(brw.find_elements(By.CLASS_NAME, 'link--alt'))

        # stop if we have reached (or overflowed) the expected amount of elements
        if currentElements >= elementsToBeFound:
            break

        # scroll to the very bottom – this triggers lazy loading on modern Cookidoo pages
        brw.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_TO)

        # some regional pages still expose an explicit "Load more recipes" button.
        # the selector switched from id="load-more-page" to data-cy="load-more-button".
        try:
            load_more_btn = brw.find_element(By.CSS_SELECTOR, 'button[data-cy="load-more-button"]')
            if load_more_btn.is_displayed():
                # Scroll the button into view – sometimes it sits just below the fold
                try:
                    brw.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_btn)
                except Exception:
                    pass  # ignore if scroll fails – click may still work

                # Use JS click for higher success rate (native click may be intercepted)
                try:
                    brw.execute_script("arguments[0].click();", load_more_btn)
                except Exception:
                    # Fallback to the traditional Selenium click
                    try:
                        load_more_btn.click()
                    except Exception:
                        pass  # give up – will retry on next loop

                time.sleep(PAGELOAD_TO)
        except Exception:
            # fallback to the legacy id-based selector (older deployments)
            try:
                brw.find_element(By.ID, 'load-more-page').click()
                time.sleep(PAGELOAD_TO)
            except Exception:
                pass  # nothing to click – rely on infinite scroll only

        print('Scrolling [{}/{}]'.format(currentElements, "∞" if elementsToBeFound == 10**9 else elementsToBeFound))

        # stop if no new tiles were injected for MAX_SCROLL_RETRIES consecutive rounds
        retry_counter = retry_counter + 1 if previousElements == currentElements else 0
        if retry_counter >= MAX_SCROLL_RETRIES:
            break

        previousElements = currentElements

    print('Scrolling completed. Total tiles found: {}'.format(previousElements))

    # saving all recipes urls
    els = brw.find_elements(By.CLASS_NAME, 'link--alt')
    recipesURLs = []
    for el in els:
        recipeURL = el.get_attribute('href')
        recipesURLs.append(recipeURL)
        recipeID = recipeURL.split('/')[-1:][0]
        brw.execute_script("arguments[0].setAttribute(arguments[1], arguments[2]);", el, 'href', './recipes/{}.html'.format(recipeID))

    # removing search bar
    try: brw.execute_script("var element = arguments[0];element.parentNode.removeChild(element);", brw.find_element(By.TAG_NAME, 'core-search-bar'))
    except: pass

    # removing scripts
    for s in brw.find_elements(By.TAG_NAME, 'script'):
        try: brw.execute_script("var element = arguments[0];element.parentNode.removeChild(element);", s)
        except: pass

    # saving the list to file
    listToFile(brw, outputdir)

    # filter recipe Url list because it contains terms-of-use, privacy, disclaimer links too
    recipesURLs = [l for l in recipesURLs if 'recipe' in l]

    # --------------------------------------------------------------
    # Always attempt explicit page navigation to capture recipes that
    # infinite-scroll/Load-more may have skipped. We stop when visiting
    # a page yields no new recipe links for two consecutive pages.
    # --------------------------------------------------------------
    print("[CD] Starting explicit page-by-page navigation to ensure completeness…")

    consecutive_empty_pages = 0
    # Use whatever URL is currently in the browser (this includes any
    # filter parameters the user might have applied) as the base.
    base_search_url = brw.current_url.split('#')[0]  # strip hash if any

    # If a &page= already exists, remove it so we can append our own.
    import re as _re_clean
    base_search_url = _re_clean.sub(r'[&?]page=\d+', '', base_search_url)

    # Ensure there is a query delimiter before appending new params
    qry_delim = '&' if '?' in base_search_url else '?'

    page_num = 2  # we already handled the first page above

    while consecutive_empty_pages < 2:
        page_url = f"{base_search_url}{qry_delim}page={page_num}"
        print(f"[CD] Navigating to search page {page_num}: {page_url}")

        brw.get(page_url)
        time.sleep(PAGELOAD_TO)

        # trigger lazy loading on this explicit page as well
        previous_height = 0
        scroll_retries = 0
        while True:
            brw.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_TO)
            curr_height = brw.execute_script("return document.body.scrollHeight")
            if curr_height == previous_height:
                scroll_retries += 1
                if scroll_retries >= MAX_SCROLL_RETRIES:
                    break
            else:
                scroll_retries = 0
            previous_height = curr_height

        # collect recipe links on this page
        page_els = brw.find_elements(By.CLASS_NAME, 'link--alt')
        new_links = 0
        for el in page_els:
            recipeURL = el.get_attribute('href')
            if recipeURL and 'recipe' in recipeURL and recipeURL not in recipesURLs:
                recipesURLs.append(recipeURL)
                new_links += 1

        print(f"[CD] Added {new_links} new recipes on page {page_num}. Total so far: {len(recipesURLs)}")

        if new_links == 0:
            consecutive_empty_pages += 1
        else:
            consecutive_empty_pages = 0

        page_num += 1

    # --------------------------------------------------------------
    print(f"[CD] Finished pagination. Total unique recipes collected: {len(recipesURLs)}")
    # --------------------------------------------------------------
    
    # getting all recipes
    print("Getting all recipes...")
    c = 0
    recipeData = []
    for recipeURL in recipesURLs:
        try:
            # building urls
            u = str(urlparse(recipeURL).path)
            if u[0] == '/': u = '.'+u
            recipeID = u.split('/')[-1:][0]
            # opening recipe url
            brw.get(recipeURL)
            time.sleep(PAGELOAD_TO)
            # removing the base href header
            try: brw.execute_script("var element = arguments[0];element.parentNode.removeChild(element);", brw.find_element(By.TAG_NAME, 'base'))
            except: pass
            # removing the name
            brw.execute_script("var element = arguments[0];element.parentNode.removeChild(element);", brw.find_element(By.TAG_NAME, 'core-user-profile'))
            # changing the top url
            brw.execute_script("arguments[0].setAttribute(arguments[1], arguments[2]);", brw.find_element(By.CLASS_NAME, 'page-header__home'), 'href', '../../index.html')
            # saving recipe image
            img_url = brw.find_element(By.ID, 'recipe-card__image-loader').find_element(By.TAG_NAME, 'img').get_attribute('src')
            local_img_path = imgToFile(outputdir, recipeID, img_url)
            # change the image url to local
            brw.execute_script("arguments[0].setAttribute(arguments[1], arguments[2]);", brw.find_element(By.CLASS_NAME, 'core-tile__image'), 'srcset', '')
            brw.execute_script("arguments[0].setAttribute(arguments[1], arguments[2]);", brw.find_element(By.CLASS_NAME, 'core-tile__image'), 'src', local_img_path)
            # saving the file
            recipeToFile(brw, '{}recipes/{}.html'.format(outputdir, recipeID))
            # extracting JSON info
            recipe = recipeToJSON(brw, recipeID)
            # saving JSON file, if needed
            if separate_json:
                print('[CD] Writing recipe to JSON file')
                with open('{}recipes/{}.json'.format(outputdir, recipeID), 'w') as outfile: json.dump(recipe, outfile)
            else:
                recipeData.append(recipe)
            # printing information
            c += 1
            if c % 10 == 0: print('Dumped recipes: {}/{}'.format(c, len(recipesURLs)))
        except: pass

    # save JSON file, if needed
    if not separate_json:
        print('[CD] Writing recipes to JSON file')
        with open('{}data.json'.format(outputdir), 'w') as outfile: json.dump(recipeData, outfile)

    # logging out
    logoutURL = f"{rootURL}/profile/logout"
    if language_code:
        logoutURL += f"/{language_code}"
    brw.get(logoutURL)
    time.sleep(PAGELOAD_TO)

    # closing session
    print('[CD] Closing session\n[CD] Goodbye!')
    brw.close()

if  __name__ =='__main__':
    parser = argparse.ArgumentParser(description='Dump Cookidoo recipes from a valid account')
    parser.add_argument('webdriverfile', type=str, help='the path to the Chrome WebDriver file')
    parser.add_argument('outputdir', type=str, help='the output directory')
    parser.add_argument('-s', '--separate-json', action='store_true', help='Create a separate JSON file for each recipe; otherwise, a single data file will be generated')
    args = parser.parse_args()
    run(args.webdriverfile, args.outputdir, args.separate_json)
