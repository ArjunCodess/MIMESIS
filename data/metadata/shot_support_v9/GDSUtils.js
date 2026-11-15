"use strict";

//*****************************************
// GDS Utility Code 
//  Assumes jquery
//
//*****************************************

//**** Utilities ****
// Read a page's GET URL variables and return them as an associative array.
$.extend({
    getUrlVars: function () {
        var vars = [], hash;
        var hashes = window.location.href.slice(window.location.href.indexOf('?') + 1).split('&');
        for (var i = 0; i < hashes.length; i++) {
            hash = hashes[i].split('=');
            vars.push(hash[0]);
            vars[hash[0]] = hash[1];
        }
        return vars;
    },
    getUrlVar: function (name) {
        return $.getUrlVars()[name];
    }
});
function strStartsWith(str, prefix) {
    return str.indexOf(prefix) === 0;
}
function formatIntegerToString(inInt) {
    var myStr0 = inInt + "";
    var myStr = "";

    //First, remove any decimal places
    for (var i = 0; i < myStr0.length; i++) {
        var myChar = myStr0.substring(i, i + 1);
        if (myChar != ".") {
            myStr = myStr + myChar;
        }
        else {
            break;
        }
    }

    //Now format
    var myResult = "";
    var myStepCount = 0;
    for (var i = myStr.length - 1; i >= 0; i--) {
        var myChar = myStr.substring(i, i + 1);
        if (myStepCount == 3) {
            myResult = "," + myResult;
            myStepCount = 0;
        }
        myResult = myChar + myResult;
        myStepCount = myStepCount + 1;
    }
    return myResult;
}
function formatRealToString(inReal, inNumberDecimalPlaces) {
    var myStr0 = inReal + "";
    var myStr = "";
    var myStrD = "";

    //First, remove any excess decimal places
    var myCount = 0;
    for (var i = 0; i < myStr0.length; i++) {
        var myChar = myStr0.substring(i, i + 1);
        if (myChar != ".") {
            if (myCount > 0) {
                if (myCount > inNumberDecimalPlaces)
                    break;
                myStrD = myStrD + myChar;
                myCount++;
            }
            else {
                myStr = myStr + myChar;
            }
        }
        else {
            myStrD = myStrD + myChar;
            myCount++;
        }
    }

    //Now format
    var myResult = "";
    var myStepCount = 0;
    for (var i = myStr.length - 1; i >= 0; i--) {
        var myChar = myStr.substring(i, i + 1);
        if (myStepCount == 3) {
            myResult = "," + myResult;
            myStepCount = 0;
        }
        myResult = myChar + myResult;
        myStepCount = myStepCount + 1;
    }
    return myResult + myStrD;
}
function ScrollPage() {
    var pageHeight = document.body.scrollHeight;
    window.scrollTo(0, pageHeight);
}
function numberToMonth(monthNumber) {
    if (monthNumber === 1)
        return "Jan";
    if (monthNumber === 2)
        return "Feb";
    if (monthNumber === 3)
        return "Mar";
    if (monthNumber === 4)
        return "Apr";
    if (monthNumber === 5)
        return "May";
    if (monthNumber === 6)
        return "Jun";
    if (monthNumber === 7)
        return "Jul";
    if (monthNumber === 8)
        return "Aug";
    if (monthNumber === 9)
        return "Sep";
    if (monthNumber === 10)
        return "Oct";
    if (monthNumber === 11)
        return "Nov";
    if (monthNumber === 12)
        return "Dec";
    return "Unk";
}

//dms added 5/25/18
function isNumberKey(evt)
{
   var charCode = (evt.which) ? evt.which : event.keyCode
   if (charCode > 31 && (charCode < 48 || charCode > 57))
      return false;

   return true;
}

function verifyInt(itemInQuestion) {
    var currentItem = document.getElementById(itemInQuestion);
    if (currentItem.value.length > 0)
    {
    var isInt = true;
    isInt = Number.isInteger(Number(currentItem.value));
    if (isInt == false) {
        currentItem.value = "";
    }
    }
}


//**** End Utilities ****